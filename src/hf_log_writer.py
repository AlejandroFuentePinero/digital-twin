"""HuggingFace-Dataset-backed log writer for the production Space (issue #46).

Two pieces:

- ``LogBuffer`` — pure data, in-memory list with a JSONL fallback at
  ``data/logs/.hf_buffer.jsonl``. The fallback exists so an unflushed
  buffer survives a Space restart; it is not the canonical store.

- ``HFLogWriter`` — non-blocking ``append`` (no network call on the hot
  path), with a flush policy of ``size >= FLUSH_BATCH_SIZE`` OR
  ``elapsed >= FLUSH_INTERVAL_SECONDS``. Each flush groups records by UTC
  date and uploads to ``logs/YYYY-MM-DD.jsonl`` in the configured HF
  Dataset repo, fetching the existing day-file first so a re-flush
  appends rather than overwrites. Reader-side dedup
  (``HFLogReader.read``) is the dedup choke point — write-side never
  tries to be exactly-once.

ADR-0002 motivates the HF Dataset backend. Slice A (#46) introduced
the buffer + writer + background poller. Slice B (#47) closes the
durability gap: ``__init__`` flushes immediately if the disk buffer
was non-empty at construction (crash recovery), and ``app.py`` wires
a SIGTERM handler so a Space restart drains the buffer before the
process dies. ``atexit`` registration of ``stop`` is handled by
``make_log_writer`` and stays the route for ordinary clean exits.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time as _time
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable

from huggingface_hub import HfApi
from huggingface_hub.utils import EntryNotFoundError

_log = logging.getLogger(__name__)

FLUSH_BATCH_SIZE = 50
FLUSH_INTERVAL_SECONDS = 600

DEFAULT_BUFFER_PATH = (
    Path(__file__).parent.parent / "data" / "logs" / ".hf_buffer.jsonl"
)


class LogBuffer:
    """In-memory record buffer with a JSONL fallback on disk.

    The disk file is the recovery story — if the process crashes after
    ``append`` but before a flush, a new instance pointed at the same
    path picks the records up. ``flush`` drains both layers atomically:
    in-memory list reset + disk file truncated. The clock used for
    ``time_since_last_flush`` is overridable for tests.
    """

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = _time.monotonic,
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
        self._records: list[dict] = []
        self._last_flush_monotonic = self._clock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self._records.append(json.loads(line))

    def append(self, record: dict) -> None:
        with self._lock:
            self._records.append(record)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._records)

    def flush(self) -> list[dict]:
        with self._lock:
            drained = list(self._records)
            self._records.clear()
            if self._path.exists():
                self._path.unlink()
            self._last_flush_monotonic = self._clock()
            return drained

    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def is_full(self, threshold: int) -> bool:
        return self.size() >= threshold

    def time_since_last_flush(self) -> float:
        return self._clock() - self._last_flush_monotonic


class HFLogWriter:
    """Buffered writer to a HuggingFace Dataset repo (one file per UTC day).

    Hot path (``append``): record goes to ``LogBuffer`` only — no HF
    call. The flush policy (``maybe_flush``) is size-or-time. The actual
    flush groups records by UTC date, fetches each day's existing file
    if any, concatenates, and uploads. Failures are logged and leave
    the buffer untouched so the next attempt re-tries.
    """

    def __init__(
        self,
        repo_id: str,
        *,
        buffer_path: Path = DEFAULT_BUFFER_PATH,
        flush_batch_size: int = FLUSH_BATCH_SIZE,
        flush_interval_seconds: float = FLUSH_INTERVAL_SECONDS,
        hf_api: HfApi | None = None,
        token: str | None = None,
        clock: Callable[[], float] = _time.monotonic,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._repo_id = repo_id
        self._batch_size = flush_batch_size
        self._interval = flush_interval_seconds
        self._api = hf_api if hf_api is not None else HfApi(token=token)
        self._token = token
        self._buffer = LogBuffer(buffer_path, clock=clock)
        self._flush_lock = threading.Lock()
        self._poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Crash recovery (#47): a non-empty buffer file at construction time
        # means the previous process died with un-shipped records. Flush
        # immediately so they're durable on HF rather than waiting up to one
        # poll tick + the size/time trigger. A failure here is logged by
        # ``flush`` itself and leaves the buffer intact for the next attempt.
        if self._buffer.size() > 0:
            self.flush()

    # ------------------------------------------------------------------ append
    def append(self, record) -> None:  # type: ignore[no-untyped-def]
        """Pipeline-facing ``append``. Accepts a dict or a Pydantic
        ``InteractionRecord`` so it slots into the existing call sites
        ``LogWriter`` already serves."""
        if hasattr(record, "model_dump"):
            record = record.model_dump()
        self._buffer.append(record)

    # ------------------------------------------------------------------- flush
    def buffer_size(self) -> int:
        return self._buffer.size()

    def maybe_flush(self) -> None:
        if self._buffer.is_full(self._batch_size):
            self.flush()
            return
        if (
            self._buffer.size() > 0
            and self._buffer.time_since_last_flush() >= self._interval
        ):
            self.flush()

    def flush(self) -> None:
        with self._flush_lock:
            records = self._buffer.snapshot()
            if not records:
                return
            try:
                self._upload_grouped_by_day(records)
            except Exception:  # broad: never let a flush fail the caller
                _log.exception(
                    "HFLogWriter flush failed; buffer of %d records preserved",
                    len(records),
                )
                return
            self._buffer.flush()

    def _upload_grouped_by_day(self, records: Iterable[dict]) -> None:
        groups: dict[date, list[dict]] = {}
        for r in records:
            day = _utc_date_of(r["timestamp"])
            groups.setdefault(day, []).append(r)

        for day, day_records in sorted(groups.items()):
            path_in_repo = f"logs/{day.isoformat()}.jsonl"
            existing = self._fetch_existing(path_in_repo)
            body = "".join(json.dumps(r) + "\n" for r in (existing + day_records))
            self._api.upload_file(
                path_or_fileobj=body.encode("utf-8"),
                path_in_repo=path_in_repo,
                repo_id=self._repo_id,
                repo_type="dataset",
                commit_message=f"Append {len(day_records)} record(s) for {day.isoformat()}",
            )

    # ------------------------------------------------------- background thread
    def start(self) -> None:
        """Start the background flush poller.

        The poller wakes every ``poll_interval_seconds`` (real wall-clock,
        via ``Event.wait``) and calls ``maybe_flush`` — which itself uses
        the injected ``clock`` to decide whether the size/time trigger
        has fired. This split keeps tests fast (mock the clock to skip
        ahead) while letting prod use the real interval.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"hf-log-flush-{self._repo_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Signal the poller to stop, wait for it to exit, and flush
        any remaining records (best-effort) so a clean shutdown
        doesn't leave un-uploaded data in the buffer."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        # Best-effort final flush. Failures are already logged by flush().
        self.flush()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.maybe_flush()
            except Exception:  # belt-and-braces — flush itself is broad
                _log.exception("HFLogWriter poll loop suppressed exception")
            if self._stop_event.wait(self._poll_interval):
                return

    def _fetch_existing(self, path_in_repo: str) -> list[dict]:
        try:
            local = self._api.hf_hub_download(
                repo_id=self._repo_id,
                filename=path_in_repo,
                repo_type="dataset",
            )
        except (EntryNotFoundError, FileNotFoundError):
            return []
        except Exception as exc:
            # Treat as "no existing file" but warn — this is the same
            # error class as a transient 5xx and we don't want to raise
            # it back into ``flush`` and clobber the buffer.
            _log.warning("Could not fetch existing %s (%s); treating as empty", path_in_repo, exc)
            return []
        return [
            json.loads(line)
            for line in Path(local).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _utc_date_of(timestamp: str) -> date:
    """Parse an ISO-8601 timestamp and return its UTC date."""
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def install_sigterm_handler(writer) -> bool:  # type: ignore[no-untyped-def]
    """Wire ``writer.stop`` into a SIGTERM handler so a Space restart
    final-flushes the buffer before the process dies (#47).

    Returns ``True`` if a handler was installed, ``False`` otherwise. Local
    backends (``LogWriter``) have no ``stop`` method and degrade to no-op
    so dev workflows are unaffected. ``atexit`` already covers the clean
    Python-exit path via ``make_log_writer``; this covers SIGTERM, which
    is what HF Spaces sends on container shutdown.
    """
    if not hasattr(writer, "stop"):
        return False

    def _handle_sigterm(_signum, _frame):
        try:
            writer.stop()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    return True

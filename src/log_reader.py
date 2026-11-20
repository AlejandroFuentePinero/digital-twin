"""Sentinel-facing typed reader over the canonical interaction log (issue #28).

Returns parsed `InteractionRecord` objects (vs `interaction_log.LogReader` which
returns dicts and pairs with `LogWriter`). `LocalReader` reads JSONL today;
`HFLogReader` (Phase 6 / `#46`) reads the per-UTC-day files written by
`HFLogWriter` from the configured HuggingFace Dataset repo.

`make_log_reader()` (Phase 6 / `#48 #49`) is the Sentinel-facing factory:
`HF_TOKEN` + `HF_DATASET_REPO` set → `HFLogReader`; otherwise → `LocalReader`.
The `force_local` argument is the `--local` CLI escape hatch.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from interaction_log import DEFAULT_LOG_PATH, SCHEMA_VERSION, InteractionRecord
from rules import GAP_PHRASE
from schema_migrations import SchemaVersionHandler

_log = logging.getLogger(__name__)


class LogReadError(RuntimeError):
    """The log could not be read in full (a failed listing or day-file
    download). Raised instead of returning a partial list, so a reader of
    the log never mistakes missing data for a quiet period (issue #61)."""


@dataclass
class ReadReport:
    """What the last ``read`` saw besides the records: the files it read,
    each line it could not parse (``source:line``), and how many records
    repeated another's identity key."""
    files_read: int = 0
    unreadable_lines: list[str] = field(default_factory=list)
    duplicates: int = 0


class LogReader(Protocol):
    report: ReadReport

    def read(self, days: int | None = None) -> list[InteractionRecord]: ...


class LocalReader:
    def __init__(self, path: Path = DEFAULT_LOG_PATH):
        self._path = Path(path)
        self.report = ReadReport()

    def read(self, days: int | None = None) -> list[InteractionRecord]:
        self.report = ReadReport()
        if not self._path.exists():
            return []
        records, bad = _parse_jsonl_to_records(self._path, source=str(self._path))
        self.report = ReadReport(
            files_read=1, unreadable_lines=bad,
            duplicates=len(records) - len(_dedupe_by_identity_key(records)),
        )
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            records = [r for r in records if r.timestamp >= cutoff]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records


def _smart_normalize_event_type(record: InteractionRecord) -> InteractionRecord:
    """Read-time upgrade of pre-v4 records carrying the canonical gap phrase.

    Pre-v4 producers only emitted ``answered`` / ``refused`` even when the
    model produced a real gap-shaped response. Where the canonical
    ``GAP_PHRASE`` is present in the last accepted answer, we surface the
    record as ``event_type='gap'`` so live tabs see the real outcome shape
    without backfilling on disk.

    The rule is GAP_PHRASE-only: ``DEFLECTION_MARKERS`` is *not* retro-
    applied because pre-v4 prompts didn't carry the marker contract — the
    model wasn't instructed to begin redirects with the canonical phrasing,
    so a marker substring in a pre-v4 answer is unreliable signal.

    On-disk records are never mutated. The normalize is read-side only.
    """
    if record.schema_version == SCHEMA_VERSION:
        return record
    last = record.attempts[-1] if record.attempts else None
    if last is None or not last.get("is_acceptable", True):
        return record
    answer = last.get("answer", "") or ""
    if GAP_PHRASE not in answer:
        return record
    return record.model_copy(update={"event_type": "gap"})


_HF_LOG_PATTERN = re.compile(r"^logs/(\d{4}-\d{2}-\d{2})\.jsonl$")


class HFLogReader:
    """Reads interaction records from a HuggingFace Dataset repo.

    Records are stored one file per UTC day at ``logs/YYYY-MM-DD.jsonl``
    by ``HFLogWriter`` (see ``hf_log_writer.py``). The reader lists the
    repo, downloads the per-day files in the requested window, parses
    each line into an ``InteractionRecord``, and dedupes on
    ``(session_id, turn_index, run_id, replicate_index, timestamp)`` —
    the slice's single dedup choke point per issue #46. Including
    timestamp in the key narrows the collapse to true buffer-replay
    duplicates (identical record re-uploaded after a crash) and
    surfaces every other record verbatim, so distinct interactions
    are never silently merged.
    """

    def __init__(self, repo_id: str, *, hf_api=None, token: str | None = None) -> None:
        if hf_api is None:
            from huggingface_hub import HfApi

            hf_api = HfApi(token=token)
        self._repo_id = repo_id
        self._api = hf_api
        # Per-instance per-file memo. ``list_repo_files`` runs once, then
        # each ``logs/YYYY-MM-DD.jsonl`` is parsed on first touch and the
        # parsed records are cached. Opening multiple Sentinel panels in
        # one session re-walks the cache without re-fetching (#49). The
        # file-level granularity preserves the ``read(days=N)`` short-
        # circuit that skips downloads for files outside the window.
        # On-disk caching is delegated to ``huggingface_hub`` itself —
        # ``hf_hub_download`` already writes to ``~/.cache/huggingface/``
        # and short-circuits on revision match.
        self._file_cache: dict[str, tuple[list[InteractionRecord], list[str]]] = {}
        self._files_listed: list[str] | None = None
        self.report = ReadReport()

    def read(self, days: int | None = None) -> list[InteractionRecord]:
        if self._files_listed is None:
            try:
                self._files_listed = self._api.list_repo_files(
                    repo_id=self._repo_id, repo_type="dataset"
                )
            except Exception as exc:
                raise LogReadError(
                    f"could not list {self._repo_id}: {type(exc).__name__}: {exc}"
                ) from exc

        cutoff_date = None
        if days is not None:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

        targets: list[str] = []
        for f in self._files_listed:
            m = _HF_LOG_PATTERN.match(f)
            if not m:
                continue
            file_date = datetime.fromisoformat(m.group(1)).date()
            if cutoff_date is not None and file_date < cutoff_date:
                continue
            targets.append(f)

        records: list[InteractionRecord] = []
        bad: list[str] = []
        for filename in targets:
            if filename not in self._file_cache:
                self._file_cache[filename] = self._download_and_parse(filename)
            file_records, file_bad = self._file_cache[filename]
            records.extend(file_records)
            bad.extend(file_bad)

        deduped = _dedupe_by_identity_key(records)
        self.report = ReadReport(
            files_read=len(targets), unreadable_lines=bad,
            duplicates=len(records) - len(deduped),
        )

        if days is not None:
            cutoff_iso = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).isoformat()
            deduped = [r for r in deduped if r.timestamp >= cutoff_iso]

        deduped.sort(key=lambda r: r.timestamp, reverse=True)
        return deduped

    def invalidate_cache(self) -> None:
        """Clear the in-memory memos so the next ``read`` re-lists the
        repo and re-parses each file. Sentinel's Refresh button calls
        this when the operator wants to pick up records appended since
        the session opened."""
        self._file_cache.clear()
        self._files_listed = None

    def _download_and_parse(self, filename: str) -> tuple[list[InteractionRecord], list[str]]:
        try:
            local = self._api.hf_hub_download(
                repo_id=self._repo_id, filename=filename, repo_type="dataset"
            )
        except Exception as exc:
            raise LogReadError(
                f"could not download {filename}: {type(exc).__name__}: {exc}"
            ) from exc
        return _parse_jsonl_to_records(Path(local), source=filename)


def _parse_jsonl_to_records(path: Path, *, source: str) -> tuple[list[InteractionRecord], list[str]]:
    """Shared parse path for both `LocalReader` and `HFLogReader`.

    Each line is JSON-decoded → run through ``SchemaVersionHandler`` to
    upgrade pre-current-version records (fill optional fields added by
    later schema bumps; raise on missing required) → validated into
    ``InteractionRecord`` → smart-normalized for pre-v4 GAP_PHRASE
    surfacing. Any of those steps can raise; ``ValueError`` (which
    ``MissingRequiredFieldError`` subclasses) and ``JSONDecodeError``
    are caught here and become a skip-with-warning so one bad line
    can't take down a read. Each skipped line is returned as ``source:line``
    so the caller can report it.
    """
    out: list[InteractionRecord] = []
    bad: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                migrated = SchemaVersionHandler(raw)
                record = InteractionRecord.model_validate(migrated)
            except (json.JSONDecodeError, ValueError) as exc:
                _log.warning("Skipping malformed log line %s:%d (%s)", source, lineno, exc)
                bad.append(f"{source}:{lineno}")
                continue
            out.append(_smart_normalize_event_type(record))
    return out, bad


def _dedupe_by_identity_key(
    records: list[InteractionRecord],
) -> list[InteractionRecord]:
    """Collapse records with the same identity tuple to one.

    Key: ``(session_id, turn_index, run_id, replicate_index, timestamp)``.
    The timestamp is part of the key so the dedup only collapses true
    buffer-replay duplicates — the writer's at-least-once delivery
    pattern (HF upload succeeds, process killed before
    ``LogBuffer.flush()`` clears local state, restart re-uploads the
    same in-memory record with its original timestamp). Distinct
    records that happen to share ``(session_id, turn_index)`` — e.g.
    two visitors who hit the Space before clicking "New conversation"
    and shared a default ``gr.State`` value — have different
    timestamps and are kept separately, so Sentinel surfaces every
    real interaction.

    Live records have ``run_id == None`` and ``replicate_index == None``;
    canary records have both populated. The first occurrence wins so
    the dedup is order-stable; downstream sort puts most-recent first.
    """
    seen: dict[tuple, InteractionRecord] = {}
    for r in records:
        key = (r.session_id, r.turn_index, r.run_id, r.replicate_index, r.timestamp)
        if key not in seen:
            seen[key] = r
    return list(seen.values())


# Backward-compatible alias for any in-flight imports — `HFReader` was the
# Phase 6 stub name in #28; #46 ships the real implementation as
# `HFLogReader` (matching the writer's `HFLogWriter`).
HFReader = HFLogReader


def make_log_reader(*, force_local: bool = False) -> LogReader:
    """Sentinel-facing reader factory (#49 / Phase 6 slice D).

    Selection rule:
    - ``force_local=True`` → ``LocalReader`` regardless of env (the
      ``--local`` CLI escape hatch when the operator wants to inspect
      dev logs in a session that also has HF creds in the environment).
    - ``HF_TOKEN`` set → ``HFLogReader`` against ``HF_DATASET_REPO``.
      Missing repo raises ``RuntimeError`` so a half-configured prod env
      fails loudly at startup rather than silently degrading to local.
    - Otherwise → ``LocalReader``.

    Mirrors the structure of ``interaction_log.make_log_writer`` so a
    Space provisioned with ``HF_TOKEN`` + ``HF_DATASET_REPO`` reads and
    writes against the same dataset without per-call configuration.
    """
    if force_local:
        return LocalReader()

    token = os.environ.get("HF_TOKEN")
    if not token:
        return LocalReader()

    repo_id = os.environ.get("HF_DATASET_REPO")
    if not repo_id:
        raise RuntimeError(
            "HF_TOKEN is set but HF_DATASET_REPO is not — make_log_reader "
            "needs both to read against the production HuggingFace Dataset. "
            "Either set HF_DATASET_REPO or pass force_local=True / --local."
        )
    return HFLogReader(repo_id=repo_id, token=token)

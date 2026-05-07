"""HuggingFace-Dataset-backed contact-form writer + reader (issue #50).

The contact-form side-channel from #16 lands `ContactRecord`s carrying
visitor email/notes joinable to `interactions.jsonl` on `session_id`.
Pre-Phase 6 these landed at `data/logs/contacts.jsonl` only — fine for
local dev but lossy on every HF Space restart, the same problem the
interaction log had before #46.

Slice E ports the same buffered-writer + reader pattern to the contact
log:

- `HFContactWriter` subclasses `HFLogWriter` (slice A) so it inherits
  the entire buffered + non-blocking append + size/interval flush +
  background poller + crash-recovery + SIGTERM-drain machinery for
  free. The two class-level differences are `PATH_PREFIX = "contacts/"`
  (so commits land at `contacts/YYYY-MM-DD.jsonl` rather than
  `logs/...`) and `WRITES_STATE_FILE = False` (contact volume is too
  low for the slice-D staleness signal to be meaningful — defer until
  the operator asks for it). Buffer file at
  `data/logs/.hf_contact_buffer.jsonl` so it doesn't collide with the
  interaction-log buffer.

- `HFContactReader` is a fresh class (the reader logic differs more
  than the writer's: different per-day-file regex, different dedup
  key — `(session_id, timestamp)` per the spec, no schema-migration
  layer because `ContactRecord` has only ever had v1).

Both pair with the `make_contact_writer` / `make_contact_reader`
factories in `contact_log.py`, which select between the local-JSONL
classes and these HF classes based on `DIGITAL_TWIN_LOG_BACKEND` /
`HF_TOKEN` (mirroring `make_log_writer` / `make_log_reader`).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from huggingface_hub import HfApi

from contact_log import ContactRecord
from hf_log_writer import (
    DEFAULT_BUFFER_PATH as _DEFAULT_LOG_BUFFER_PATH,
    HFLogWriter,
)

_log = logging.getLogger(__name__)

# Separate buffer file so the contact-form writer's un-flushed records
# don't collide with the interaction-log writer's. Both live under
# `data/logs/` (gitignored) and are independently truncated by their
# owners' flush.
DEFAULT_CONTACT_BUFFER_PATH = (
    _DEFAULT_LOG_BUFFER_PATH.parent / ".hf_contact_buffer.jsonl"
)


class HFContactWriter(HFLogWriter):
    """Buffered writer for `ContactRecord` against the production HF
    Dataset (#50). Inherits all flush / thread / crash-recovery /
    SIGTERM-drain semantics from `HFLogWriter`; differs only in the
    repo path prefix and the deliberate skip of the diagnostic state
    file (see module docstring)."""

    PATH_PREFIX: str = "contacts/"
    WRITES_STATE_FILE: bool = False

    def __init__(
        self,
        repo_id: str,
        *,
        buffer_path: Path = DEFAULT_CONTACT_BUFFER_PATH,
        **kwargs,
    ) -> None:
        super().__init__(repo_id, buffer_path=buffer_path, **kwargs)


_HF_CONTACT_PATTERN = re.compile(r"^contacts/(\d{4}-\d{2}-\d{2})\.jsonl$")


class HFContactReader:
    """Reads contact records from the production HF Dataset.

    Records are stored one file per UTC day at
    ``contacts/YYYY-MM-DD.jsonl`` by ``HFContactWriter``. The reader
    lists the repo, downloads the per-day files, parses each line, and
    dedupes on ``(session_id, timestamp)`` — the slice's dedup key
    (records with the same session_id + timestamp are exact replays of
    a flush retry; collapse them).

    Per-instance caching mirrors ``HFLogReader`` (#49): the first
    ``read_all()`` lists the repo + downloads files once; subsequent
    calls re-walk the cache. ``invalidate_cache()`` is the Refresh-
    button hook.
    """

    def __init__(
        self,
        repo_id: str,
        *,
        hf_api: HfApi | None = None,
        token: str | None = None,
    ) -> None:
        if hf_api is None:
            hf_api = HfApi(token=token)
        self._repo_id = repo_id
        self._api = hf_api
        self._file_cache: dict[str, list[dict]] = {}
        self._files_listed: list[str] | None = None

    def read_all(self) -> list[dict]:
        """Returns all contact records as dicts, deduped on
        ``(session_id, timestamp)``. Dict shape (rather than typed
        ``ContactRecord``) matches ``ContactReader.read_all`` so
        ``read_provided_session_ids`` and any other consumers stay
        backend-agnostic."""
        if self._files_listed is None:
            try:
                self._files_listed = self._api.list_repo_files(
                    repo_id=self._repo_id, repo_type="dataset"
                )
            except Exception:
                _log.exception(
                    "HFContactReader could not list repo %s", self._repo_id
                )
                self._files_listed = []
                return []

        targets = [f for f in self._files_listed if _HF_CONTACT_PATTERN.match(f)]

        records: list[dict] = []
        for filename in targets:
            if filename not in self._file_cache:
                self._file_cache[filename] = self._download_and_parse(filename)
            records.extend(self._file_cache[filename])

        return _dedupe_by_session_and_timestamp(records)

    def read(self) -> list[ContactRecord]:
        """Typed convenience: parse each record dict into a
        ``ContactRecord``. Symmetric with ``log_reader.HFLogReader.read``;
        Sentinel uses ``read_all`` today but a future surface may want
        the typed model."""
        return [ContactRecord.model_validate(r) for r in self.read_all()]

    def invalidate_cache(self) -> None:
        self._file_cache.clear()
        self._files_listed = None

    def _download_and_parse(self, filename: str) -> list[dict]:
        try:
            local = self._api.hf_hub_download(
                repo_id=self._repo_id, filename=filename, repo_type="dataset"
            )
        except Exception as exc:
            _log.warning("HFContactReader skipping %s (%s)", filename, exc)
            return []
        out: list[dict] = []
        for lineno, line in enumerate(
            Path(local).read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                _log.warning(
                    "Skipping malformed contact line %s:%d (%s)", filename, lineno, exc
                )
        return out


def _dedupe_by_session_and_timestamp(records: list[dict]) -> list[dict]:
    """Collapse exact replays. A contact record is identified by
    ``(session_id, timestamp)`` — two records with the same key are
    a flush retry; the first occurrence wins so the dedup is
    order-stable (no per-call timestamp variance to chase)."""
    seen: dict[tuple, dict] = {}
    for r in records:
        key = (r.get("session_id"), r.get("timestamp"))
        if key not in seen:
            seen[key] = r
    return list(seen.values())

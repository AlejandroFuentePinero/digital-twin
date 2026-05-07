"""Sentinel-facing typed reader over the canonical interaction log (issue #28).

Returns parsed `InteractionRecord` objects (vs `interaction_log.LogReader` which
returns dicts and pairs with `LogWriter`). `LocalReader` reads JSONL today;
`HFReader` is a Phase 6 stub per ADR-0002.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from interaction_log import DEFAULT_LOG_PATH, SCHEMA_VERSION, InteractionRecord
from rules import GAP_PHRASE

_log = logging.getLogger(__name__)


class LogReader(Protocol):
    def read(self, days: int | None = None) -> list[InteractionRecord]: ...


class LocalReader:
    def __init__(self, path: Path = DEFAULT_LOG_PATH):
        self._path = Path(path)

    def read(self, days: int | None = None) -> list[InteractionRecord]:
        if not self._path.exists():
            return []
        records: list[InteractionRecord] = []
        with self._path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    record = InteractionRecord.model_validate(json.loads(line))
                except (json.JSONDecodeError, ValueError) as exc:
                    _log.warning("Skipping malformed log line %s:%d (%s)", self._path, lineno, exc)
                    continue
                records.append(_smart_normalize_event_type(record))
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
    ``(session_id, turn_index, run_id, replicate_index)`` — the slice's
    single dedup choke point per issue #46. Canary fields default
    ``None`` for live records, so a live record's key is
    ``(session_id, turn_index, None, None)``.
    """

    def __init__(self, repo_id: str, *, hf_api=None, token: str | None = None) -> None:
        if hf_api is None:
            from huggingface_hub import HfApi

            hf_api = HfApi(token=token)
        self._repo_id = repo_id
        self._api = hf_api

    def read(self, days: int | None = None) -> list[InteractionRecord]:
        try:
            files = self._api.list_repo_files(repo_id=self._repo_id, repo_type="dataset")
        except Exception:
            _log.exception("HFLogReader could not list repo %s", self._repo_id)
            return []

        cutoff_date = None
        if days is not None:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

        targets: list[str] = []
        for f in files:
            m = _HF_LOG_PATTERN.match(f)
            if not m:
                continue
            file_date = datetime.fromisoformat(m.group(1)).date()
            if cutoff_date is not None and file_date < cutoff_date:
                continue
            targets.append(f)

        records: list[InteractionRecord] = []
        for filename in targets:
            try:
                local = self._api.hf_hub_download(
                    repo_id=self._repo_id, filename=filename, repo_type="dataset"
                )
            except Exception as exc:
                _log.warning("HFLogReader skipping %s (%s)", filename, exc)
                continue
            records.extend(_parse_jsonl_to_records(Path(local), source=filename))

        deduped = _dedupe_by_identity_key(records)

        if days is not None:
            cutoff_iso = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).isoformat()
            deduped = [r for r in deduped if r.timestamp >= cutoff_iso]

        deduped.sort(key=lambda r: r.timestamp, reverse=True)
        return deduped


def _parse_jsonl_to_records(path: Path, *, source: str) -> list[InteractionRecord]:
    out: list[InteractionRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = InteractionRecord.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValueError) as exc:
                _log.warning("Skipping malformed log line %s:%d (%s)", source, lineno, exc)
                continue
            out.append(_smart_normalize_event_type(record))
    return out


def _dedupe_by_identity_key(
    records: list[InteractionRecord],
) -> list[InteractionRecord]:
    """Collapse records with the same identity tuple to one.

    Key: ``(session_id, turn_index, run_id, replicate_index)``. Live
    records have ``run_id == None`` and ``replicate_index == None``,
    canary records have both populated. The first occurrence wins so
    the dedup is order-stable; downstream sort puts most-recent first.
    """
    seen: dict[tuple, InteractionRecord] = {}
    for r in records:
        key = (r.session_id, r.turn_index, r.run_id, r.replicate_index)
        if key not in seen:
            seen[key] = r
    return list(seen.values())


# Backward-compatible alias for any in-flight imports — `HFReader` was the
# Phase 6 stub name in #28; #46 ships the real implementation as
# `HFLogReader` (matching the writer's `HFLogWriter`).
HFReader = HFLogReader

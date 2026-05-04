"""Sentinel-facing typed reader over the canonical interaction log (issue #28).

Returns parsed `InteractionRecord` objects (vs `interaction_log.LogReader` which
returns dicts and pairs with `LogWriter`). `LocalReader` reads JSONL today;
`HFReader` is a Phase 6 stub per ADR-0002.
"""

from __future__ import annotations

import json
import logging
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


class HFReader:
    # Phase 6: HuggingFace Dataset backend per ADR-0002.
    def read(self, days: int | None = None) -> list[InteractionRecord]:
        raise NotImplementedError(
            "HFReader is a Phase 6 stub; HuggingFace Dataset backend not yet implemented (ADR-0002)."
        )

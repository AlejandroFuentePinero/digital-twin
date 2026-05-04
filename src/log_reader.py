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

from interaction_log import DEFAULT_LOG_PATH, InteractionRecord

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
                    records.append(InteractionRecord.model_validate(json.loads(line)))
                except (json.JSONDecodeError, ValueError) as exc:
                    _log.warning("Skipping malformed log line %s:%d (%s)", self._path, lineno, exc)
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            records = [r for r in records if r.timestamp >= cutoff]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records


class HFReader:
    # Phase 6: HuggingFace Dataset backend per ADR-0002.
    def read(self, days: int | None = None) -> list[InteractionRecord]:
        raise NotImplementedError(
            "HFReader is a Phase 6 stub; HuggingFace Dataset backend not yet implemented (ADR-0002)."
        )

"""Enriched per-turn interaction log (ADR-0002 / issue #13 step 7).

Replaces the pre-redesign single-purpose `logger.py`. Every Pipeline.run() call
produces one `InteractionRecord` written to JSONL via `LogWriter.append`. The
Sentinel and offline analysis read records back via `LogReader.read_all` /
`read_since`. JSONL backend today (dev); HuggingFace Dataset replaces the
storage layer in Phase 6 without changing this module's public surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_LOG_PATH = Path(__file__).parent.parent / "data" / "logs" / "interactions.jsonl"

EventType = Literal["answered", "gap", "deflected", "refused"]


class InteractionRecord(BaseModel):
    schema_version: str = "1"
    timestamp: str
    session_id: str
    turn_index: int
    question: str
    event_type: EventType
    branch: str
    classifier_labels: list[str] = Field(default_factory=list)
    classification_confidence: float
    attempts: list[dict]
    retrieved_chunks: list[dict]
    tool_calls: list[dict] = Field(default_factory=list)
    latency_ms: dict
    knew_answer: bool
    contact_offered: bool = False
    contact_provided: bool = False


class LogWriter:
    def __init__(self, path: Path = DEFAULT_LOG_PATH):
        self._path = Path(path)

    def append(self, record: dict | InteractionRecord) -> None:
        if isinstance(record, dict):
            record = InteractionRecord.model_validate(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")


class LogReader:
    def __init__(self, path: Path = DEFAULT_LOG_PATH):
        self._path = Path(path)

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def read_since(self, since: str) -> list[dict]:
        """Return records with `timestamp >= since` (lex-compare ISO-8601 strings)."""
        return [r for r in self.read_all() if r["timestamp"] >= since]

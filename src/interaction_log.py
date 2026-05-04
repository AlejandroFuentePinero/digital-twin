"""Enriched per-turn interaction log (ADR-0002 / issue #13 step 7).

Replaces the pre-redesign single-purpose `logger.py`. Every Pipeline.run() call
produces one `InteractionRecord` written to JSONL via `LogWriter.append`. The
Sentinel and offline analysis read records back via `LogReader.read_all` /
`read_since`. JSONL backend today (dev); HuggingFace Dataset replaces the
storage layer in Phase 6 without changing this module's public surface.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_LOG_PATH = Path(__file__).parent.parent / "data" / "logs" / "interactions.jsonl"

# Single source of truth for the on-disk schema. Bumped to v4 in #42 when the
# producer started emitting all four EventType values via event_classifier.
# Both the pipeline writer and LogReader's smart-normalize key off this — a
# future bump is a one-line change here.
SCHEMA_VERSION = "4"

EventType = Literal["answered", "gap", "deflected", "refused"]


def compute_prompt_hash(system: str, user: str) -> str:
    """SHA-256[:12] over system+user. Distinguishes 'same question, different
    rule set' at log level without storing the full prompt — the prompt is
    reconstructable from `git_sha` + `composer.py` + branch + chunks."""
    return hashlib.sha256((system + user).encode()).hexdigest()[:12]


class InteractionRecord(BaseModel):
    schema_version: str = SCHEMA_VERSION
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
    # Reproducibility fields (issue #37). Optional + None-defaulted so legacy
    # v1 records still parse. git_sha/model_id/temperature/prompt_hash together
    # let trend shifts be correlated with code/model/prompt changes and let a
    # failed turn be replayed under its original conditions.
    git_sha: str | None = None
    model_id: str | None = None
    temperature: float | None = None
    prompt_hash: str | None = None
    # Canary fields (issue #39, schema v3 bump). Default to live-record shape
    # (is_canary=False, replicate_index/run_id=None) so legacy v2 records still
    # parse. Populated by canary_runner.py when replaying the corpus.
    is_canary: bool = False
    replicate_index: int | None = None
    run_id: str | None = None


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

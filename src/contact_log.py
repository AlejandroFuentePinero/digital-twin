"""Contact-form record schema + JSONL writer/reader (#16).

Parallel structure to `interaction_log.LogWriter` / `LogReader`. Records the
contact-form submissions from the app's collapsible row that appears at the
configured invitation turn (default 3). Each record carries `session_id` as
the join key — paired with `interactions.jsonl` records on the same
`session_id`, the conversation that led to the contact request can be
reconstructed.

JSONL backend today (dev); HuggingFace Dataset replaces the storage layer in
Phase 6 without changing this module's public surface (same as `interaction_log`).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

DEFAULT_CONTACT_LOG_PATH = Path(__file__).parent.parent / "data" / "logs" / "contacts.jsonl"


class ContactRecord(BaseModel):
    schema_version: str = "1"
    timestamp: str
    session_id: str
    turn_index: int
    email: str
    name: str | None = None
    note: str | None = None


class ContactWriter:
    def __init__(self, path: Path = DEFAULT_CONTACT_LOG_PATH):
        self._path = Path(path)

    def append(self, record: dict | ContactRecord) -> None:
        if isinstance(record, dict):
            record = ContactRecord.model_validate(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")


class ContactReader:
    def __init__(self, path: Path = DEFAULT_CONTACT_LOG_PATH):
        self._path = Path(path)

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

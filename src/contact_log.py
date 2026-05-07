"""Contact-form record schema + JSONL writer/reader (#16).

Parallel structure to `interaction_log.LogWriter` / `LogReader`. Records the
contact-form submissions from the app's collapsible row that appears at the
configured invitation turn (default 3). Each record carries `session_id` as
the join key — paired with `interactions.jsonl` records on the same
`session_id`, the conversation that led to the contact request can be
reconstructed.

JSONL backend for local dev; the `make_contact_writer` / `make_contact_reader`
factories (Phase 6 / `#50`) select between this and the HuggingFace
Dataset-backed `HFContactWriter` / `HFContactReader` (in
`hf_contact_log.py`) based on `DIGITAL_TWIN_LOG_BACKEND` (writer) or
`HF_TOKEN` + `HF_DATASET_REPO` (reader). Mirrors the structure of
`interaction_log.make_log_writer` and `log_reader.make_log_reader` so a
Space provisioned with HF env reads and writes both contact records and
interaction records to the same dataset.
"""

from __future__ import annotations

import atexit
import json
import os
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


def read_provided_session_ids(
    path: Path | None = None,
    *,
    reader: object | None = None,
) -> set[str]:
    """Set of `session_id`s that submitted the contact form.

    Cross-reference target for ``DashboardModel.contact_conversion_rate``.
    Required because the live writer sets ``contact_provided=True`` on the
    InteractionRecord *after* the form is submitted, so a record never
    carries both ``contact_offered=True`` and ``contact_provided=True``;
    record-level intersection always returns 0%. Joining on ``session_id``
    gives the true conversion: a session that was offered the form AND has
    an entry in ``contacts.jsonl`` counts as converted.

    Backend selection (#50): if ``reader`` is passed, use it directly.
    Else if ``path`` is passed, use a `ContactReader` against that path
    (back-compat for tests pinning the local file). Else fall back to
    `make_contact_reader()` so Sentinel running against the HF backend
    sees contacts uploaded to the dataset."""
    if reader is not None:
        records = reader.read_all()
    elif path is not None:
        records = ContactReader(path).read_all()
    else:
        records = make_contact_reader().read_all()
    return {r["session_id"] for r in records}


def make_contact_writer(
    *,
    local_path: Path = DEFAULT_CONTACT_LOG_PATH,
    buffer_path: Path | None = None,
    auto_start: bool = True,
):
    """Pipeline-facing contact-writer factory (#50). Mirrors
    ``interaction_log.make_log_writer``: ``DIGITAL_TWIN_LOG_BACKEND=local``
    (or unset) → file-backed ``ContactWriter`` against
    ``contacts.jsonl``; ``=hf`` → ``HFContactWriter`` pointed at
    ``HF_DATASET_REPO`` with the background flush thread started and
    an ``atexit`` hook that stops + final-flushes on shutdown.
    Misconfiguration raises at startup rather than silently degrading.

    ``auto_start=False`` is an escape hatch for tests that want to
    drive the writer synchronously."""
    backend = os.environ.get("DIGITAL_TWIN_LOG_BACKEND", "local").lower()
    if backend == "local":
        return ContactWriter(local_path)
    if backend == "hf":
        repo_id = os.environ.get("HF_DATASET_REPO")
        if not repo_id:
            raise RuntimeError(
                "DIGITAL_TWIN_LOG_BACKEND=hf requires HF_DATASET_REPO env var "
                "(e.g. 'Alejandrofupi/digital-twin-logs')."
            )
        from hf_contact_log import DEFAULT_CONTACT_BUFFER_PATH, HFContactWriter

        writer = HFContactWriter(
            repo_id=repo_id,
            buffer_path=buffer_path or DEFAULT_CONTACT_BUFFER_PATH,
            token=os.environ.get("HF_TOKEN"),
        )
        if auto_start:
            writer.start()
            atexit.register(writer.stop)
        return writer
    raise RuntimeError(
        f"DIGITAL_TWIN_LOG_BACKEND={backend!r} is not recognised; "
        "expected 'local' or 'hf'."
    )


def make_contact_reader(*, force_local: bool = False):
    """Sentinel-facing contact-reader factory (#50). Mirrors
    ``log_reader.make_log_reader``: ``HF_TOKEN`` + ``HF_DATASET_REPO``
    set → ``HFContactReader`` against that repo; otherwise →
    ``ContactReader``. ``force_local=True`` is the operator escape
    hatch (paired with `--local` on Sentinel) when prod creds are
    exported but the operator wants to inspect dev contacts."""
    if force_local:
        return ContactReader()

    token = os.environ.get("HF_TOKEN")
    if not token:
        return ContactReader()

    repo_id = os.environ.get("HF_DATASET_REPO")
    if not repo_id:
        raise RuntimeError(
            "HF_TOKEN is set but HF_DATASET_REPO is not — make_contact_reader "
            "needs both to read against the production HuggingFace Dataset. "
            "Either set HF_DATASET_REPO or pass force_local=True."
        )
    from hf_contact_log import HFContactReader

    return HFContactReader(repo_id=repo_id, token=token)

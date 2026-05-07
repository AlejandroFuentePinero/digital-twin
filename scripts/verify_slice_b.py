"""Manual verification for slice B (#47) — crash recovery + SIGTERM.

Two-pass run:

1. Pass 1 simulates a crash: appends one record (lands in the in-memory
   buffer + the disk fallback at ``data/logs/.hf_buffer.jsonl``), then
   ``os._exit(1)`` without calling ``stop()`` — so the upload never
   happens.

2. Pass 2 reinstantiates ``HFLogWriter`` against the same buffer path.
   The new ``__init__`` logic should pick the surviving record off disk
   and flush it immediately. We then read it back through ``HFLogReader``
   to confirm it landed in the HF Dataset.

Run from repo root with:

    DIGITAL_TWIN_LOG_BACKEND=hf uv run python scripts/verify_slice_b.py

The script needs ``HF_DATASET_REPO`` + ``HF_TOKEN`` in ``.env`` and is
scoped to the configured dataset only (writes one record under a
unique session id, then reads it back).
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(override=True)


def _record(session_id: str) -> dict:
    return {
        "schema_version": "4",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "session_id": session_id,
        "turn_index": 0,
        "question": "slice-B verification",
        "event_type": "answered",
        "branch": "GENERIC",
        "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 1, "retrieval": 1, "generation": 1, "guardrail": 1, "total": 4},
        "knew_answer": True,
        "contact_offered": False,
        "contact_provided": False,
    }


def main() -> None:
    repo_id = os.environ["HF_DATASET_REPO"]
    token = os.environ["HF_TOKEN"]

    # Use a tmp buffer path so we don't disturb a real local buffer.
    buffer_path = ROOT / "data" / "logs" / ".hf_buffer_slice_b_verify.jsonl"
    buffer_path.parent.mkdir(parents=True, exist_ok=True)

    pass_n = sys.argv[1] if len(sys.argv) > 1 else "both"

    if pass_n in ("1", "both") and buffer_path.exists():
        buffer_path.unlink()

    from hf_log_writer import HFLogWriter

    if pass_n in ("1", "both"):
        # Pass 1 — simulate crash. Append, then hard-exit. The disk
        # buffer file should contain one record after this.
        session_id = f"slice-b-verify-{uuid.uuid4().hex[:8]}"
        marker_path = ROOT / "data" / "logs" / ".slice_b_session_marker.txt"
        marker_path.write_text(session_id)
        writer = HFLogWriter(
            repo_id=repo_id,
            buffer_path=buffer_path,
            flush_batch_size=50,  # high — won't trigger size flush
            flush_interval_seconds=600,
            token=token,
        )
        writer.append(_record(session_id))
        print(f"[pass 1] appended record session_id={session_id}")
        print(f"[pass 1] buffer size in memory={writer.buffer_size()}")
        print(f"[pass 1] disk buffer exists={buffer_path.exists()}")
        # Simulate crash — no stop, no flush.
        if pass_n == "1":
            os._exit(1)
        # Detach so pass-2 starts fresh; mimic restart by dropping refs.
        del writer

    if pass_n in ("2", "both"):
        marker_path = ROOT / "data" / "logs" / ".slice_b_session_marker.txt"
        session_id = marker_path.read_text().strip()
        print(f"[pass 2] starting; expected session_id={session_id}")
        print(f"[pass 2] disk buffer exists pre-init={buffer_path.exists()}")

        # The contract: __init__ alone must trigger the upload.
        writer = HFLogWriter(
            repo_id=repo_id,
            buffer_path=buffer_path,
            flush_batch_size=50,
            flush_interval_seconds=600,
            token=token,
        )
        print(f"[pass 2] buffer size in memory post-init={writer.buffer_size()}")
        print(f"[pass 2] disk buffer exists post-init={buffer_path.exists()}")

        # Read back from HF and confirm.
        from log_reader import HFLogReader

        reader = HFLogReader(repo_id=repo_id, token=token)
        records = reader.read(days=2)
        matched = [r for r in records if r.session_id == session_id]
        if matched:
            print(f"[pass 2] OK — {len(matched)} record(s) for {session_id} on HF.")
        else:
            print(f"[pass 2] FAIL — no records for {session_id} on HF.")
            sys.exit(2)

        marker_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

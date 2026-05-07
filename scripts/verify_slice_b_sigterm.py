"""SIGTERM-half manual verification for slice B (#47).

Mirrors what app.py does at startup — ``make_log_writer()`` then
``install_sigterm_handler()`` — appends one record, then waits to be
killed externally with SIGTERM. The handler should final-flush the
buffer (via writer.stop) and exit cleanly. The test harness in
``run_verify_slice_b_sigterm.sh`` is the round-trip; this is only
the child process.

Run via:

    DIGITAL_TWIN_LOG_BACKEND=hf uv run python scripts/verify_slice_b_sigterm.py <session_id> <buffer_path>
"""

from __future__ import annotations

import os
import sys
import time
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
        "question": "slice-B SIGTERM verification",
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
    session_id = sys.argv[1]
    buffer_path = Path(sys.argv[2])

    from hf_log_writer import HFLogWriter, install_sigterm_handler

    writer = HFLogWriter(
        repo_id=os.environ["HF_DATASET_REPO"],
        buffer_path=buffer_path,
        flush_batch_size=50,
        flush_interval_seconds=600,
        token=os.environ["HF_TOKEN"],
    )
    writer.start()
    installed = install_sigterm_handler(writer)
    print(f"[child] SIGTERM handler installed={installed}", flush=True)

    writer.append(_record(session_id))
    print(f"[child] appended; buffer_size={writer.buffer_size()}", flush=True)
    print("[child] ready, awaiting SIGTERM…", flush=True)

    # Idle until SIGTERM. Worst case the harness sends SIGKILL after
    # 30s and the buffer survives on disk for the next process.
    while True:
        time.sleep(0.5)


if __name__ == "__main__":
    main()

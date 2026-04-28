"""
Append-only JSONL interaction logger for the digital twin.

One record per answer_with_guardrail call. Captures every question, the answer
the user received, whether it passed the guardrail, whether the system had the
information, and how many retries were needed.

Storage: local disk at data/logs/interactions.jsonl.
TODO: replace with HuggingFace Dataset write when deploying to production.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "logs" / "interactions.jsonl"


def log_interaction(
    question: str,
    answer: str,
    is_acceptable: bool,
    knew_answer: bool,
    retry_count: int,
    session_id: str | None = None,
) -> None:
    """Append one interaction record to the JSONL log."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "question": question,
        "answer": answer,
        "is_acceptable": is_acceptable,
        "knew_answer": knew_answer,
        "retry_count": retry_count,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

"""Outcome judge for live turns (issue #63).

The twin's logged ``event_type`` follows the branch that answered, not the
answer (``LIMITATIONS::P17``). Sentinel reads the outcome from the answer
instead: the canary judge's model reads each live turn's final answer once
and labels it answered, declined, did not know or error.

Labels are cached in ``data/logs/outcome_judgements.jsonl`` (gitignored,
beside Sentinel's other caches), one line per turn keyed by the record's
timestamp and session, so each turn is judged once and nothing the twin
logs changes. A turn the judge could not label is not cached: it shows as
not yet judged and is tried again on the next run.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from litellm import completion
from pydantic import BaseModel, ValidationError

from canary_judge import JUDGE_MODEL, shown_answer
from dashboard_model import outcome_key
from interaction_log import DEFAULT_LOG_PATH, InteractionRecord

DEFAULT_OUTCOMES_PATH = DEFAULT_LOG_PATH.parent / "outcome_judgements.jsonl"
JUDGE_ATTEMPTS = 3
JUDGE_RETRY_WAIT_SECONDS = 5
JUDGE_WORKERS = 8

_SYSTEM_PROMPT = (
    "You read answers from a digital twin that represents Alejandro de la Fuente "
    "to recruiters. For each one you get the visitor's question and the answer the "
    "visitor saw. Label what the answer did, with exactly one of:\n\n"
    "- answered: it gives the visitor information that addresses the question. "
    "This includes logistical facts (where he lives, how to contact him), a "
    "greeting that says what the twin can help with, and an honest statement "
    "that he has not done something, with or without related experience.\n"
    "- declined: it does not answer because it treats the question as out of "
    "scope (personal life, opinions, general coding help, trivia, a harmful or "
    "manipulative request) and redirects to his professional background or to "
    "contacting him directly.\n"
    "- did not know: it says it does not have the information the question asks "
    "for (for example \"I don't have that information in my knowledge base\") and "
    "gives no substantive answer to the question itself.\n"
    "- error: the visitor got an error message or the canned message asking them "
    "to reach out to Alejandro directly instead of an answer.\n\n"
    "Judge what the answer does, not how long it is. When an answer both says it "
    "lacks a specific detail and answers the rest of the question with substance, "
    "it is answered."
)


class _JudgeOutput(BaseModel):
    outcome: Literal["answered", "declined", "did not know", "error"]


def judge_outcome(record: InteractionRecord) -> tuple[str | None, str | None]:
    """``(label, None)``, or ``(None, reason)`` when the judge could not label it."""
    if getattr(record, "failed_stage", None):  # failed before the retry loop (#64): no answer to read
        return "error", None
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {record.question}\n\nAnswer the visitor saw:\n{shown_answer(record)}"},
    ]
    last_error: Exception | None = None
    for attempt in range(JUDGE_ATTEMPTS):
        if attempt:
            time.sleep(JUDGE_RETRY_WAIT_SECONDS)
        try:
            response = completion(model=JUDGE_MODEL, messages=messages, response_format=_JudgeOutput)
        except Exception as exc:  # provider error: retry, then report
            last_error = exc
            continue
        try:
            return _JudgeOutput.model_validate_json(response.choices[0].message.content).outcome, None
        except ValidationError:
            return None, "judge output unreadable"
    return None, f"{type(last_error).__name__}: {last_error}"


def read_outcomes(path: Path = DEFAULT_OUTCOMES_PATH) -> dict[str, str]:
    """Every cached judgement, ``{outcome_key: label}``."""
    path = Path(path)
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["key"]: row["outcome"] for row in rows}


def judge_new_turns(
    records: list[InteractionRecord],
    path: Path = DEFAULT_OUTCOMES_PATH,
) -> str | None:
    """Judge every live turn not yet in the cache and append the labels.
    Returns a message naming the turns the judge could not label, else None."""
    done = read_outcomes(path)
    todo = [r for r in records if not r.is_canary and outcome_key(r) not in done]
    if not todo:
        return None
    with ThreadPoolExecutor(JUDGE_WORKERS) as pool:
        results = list(pool.map(judge_outcome, todo))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r, (label, _) in zip(todo, results):
            if label is not None:
                f.write(json.dumps({"key": outcome_key(r), "outcome": label}) + "\n")
    failed = [reason for label, reason in results if label is None]
    if not failed:
        return None
    return (f"Outcome judge could not label {len(failed)} {'turn' if len(failed) == 1 else 'turns'} "
            f"(they show as not yet judged): {'; '.join(sorted(set(failed)))}")

"""Canary judge (issue #53): grades one canary answer against its question's
expected behaviour and returns pass or fail with a one-line reason.

The canary is a regression test: every replicate's answer must get the right
meaning across. The judge reads the answer the visitor saw (the accepted
attempt, or the canned refusal when every attempt was rejected) and the
corpus's `expected_behaviour` description, and grades meaning, not wording.

A judge failure (unreadable output, or an API error after retries) is a
failed verdict, never a silent pass.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from litellm import completion
from pydantic import BaseModel, ValidationError

from canary_corpus import CanaryQuestion
from interaction_log import InteractionRecord
from pipeline import CANNED_REFUSAL

# Same judge as the eval (Session 71): stronger than the gpt-6.1-terra
# generator, so the generator does not grade itself. Default reasoning: it
# rejects reasoning_effort "none", and the judge makes no tool calls.
JUDGE_MODEL = "openai/gpt-6.2-sol"
JUDGE_ATTEMPTS = 3
JUDGE_RETRY_WAIT_SECONDS = 5

_SYSTEM_PROMPT = (
    "You check answers from a digital twin that represents Alejandro de la Fuente "
    "to recruiters. For each answer you get the visitor's question and a short "
    "description of what a correct answer does. Decide whether the answer meets "
    "that description.\n\n"
    "Grade meaning, not wording. Different phrasing, a different order, or extra "
    "correct detail beyond the description are all fine. A number may be rounded "
    "or formatted differently. An answer may speak about Alejandro in the first or "
    "third person. Anything the description marks with \"may\" is optional: "
    "its absence is never a reason to fail. When the correct answer is that he "
    "lacks an experience, any wording that says he has not done it counts, "
    "including softer forms such as \"no record of it\", \"no evidence of it\" "
    "or \"has not completed one\", as long as the answer does not claim the "
    "experience.\n\n"
    "Fail the answer only when it: gets a point wrong; misses the core point the "
    "description asks for; claims something the description says it must not "
    "claim; or gives the wrong kind of answer (answers when it should decline, "
    "declines or says it has no information when it should answer).\n\n"
    "Give a one-sentence reason naming what decided the verdict."
)


class _JudgeOutput(BaseModel):
    passed: bool
    reason: str


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str


def shown_answer(record: InteractionRecord) -> str:
    """The text the visitor saw: the accepted attempt, else the canned refusal."""
    for attempt in record.attempts:
        if attempt.get("is_acceptable"):
            return attempt.get("answer") or ""
    return CANNED_REFUSAL


def judge(record: InteractionRecord, question: CanaryQuestion) -> Verdict:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question: {question.question}\n\n"
                f"What a correct answer does: {question.expected_behaviour}\n\n"
                f"Answer to check:\n{shown_answer(record)}"
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(JUDGE_ATTEMPTS):
        if attempt:
            time.sleep(JUDGE_RETRY_WAIT_SECONDS)
        try:
            response = completion(
                model=JUDGE_MODEL, messages=messages, response_format=_JudgeOutput,
            )
        except Exception as exc:  # provider error: retry, then fail loudly
            last_error = exc
            continue
        try:
            out = _JudgeOutput.model_validate_json(response.choices[0].message.content)
        except ValidationError:
            return Verdict(passed=False, reason="Judge output unreadable.")
        return Verdict(passed=out.passed, reason=out.reason)
    return Verdict(passed=False, reason=f"Judge call failed: {last_error}")

"""Tests for the canary judge (issue #53). The judge model is the process
boundary and is mocked; no LLM calls run in tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from canary_corpus import CanaryQuestion
from canary_judge import Verdict, judge
from interaction_log import InteractionRecord
from pipeline import CANNED_REFUSAL


QUESTION = CanaryQuestion(
    id="C007",
    question="Tell me about your CUDA kernel work",
    expected_behaviour="Says he has no CUDA kernel experience. Does not claim any.",
    expected_chunk_sources=[],
    category="branch_routing_technical_gap",
)


def _record(attempts: list[dict]) -> InteractionRecord:
    return InteractionRecord(
        timestamp="2026-11-20T00:00:00+00:00",
        session_id="canary-run-x-C007",
        turn_index=0,
        question=QUESTION.question,
        event_type="answered",
        branch="TECHNICAL",
        classification_confidence=0.9,
        attempts=attempts,
        retrieved_chunks=[],
        latency_ms={"total": 1000},
        knew_answer=True,
        is_canary=True,
        run_id="run-x",
        replicate_index=0,
    )


def _judge_says(payload: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


def test_judge_returns_the_models_pass_verdict_and_reason():
    """The judge model's pass/fail and reason come back as the Verdict."""
    record = _record([{"answer": "I have no CUDA kernel work.", "is_acceptable": True}])
    with patch(
        "canary_judge.completion",
        return_value=_judge_says('{"passed": true, "reason": "States the gap."}'),
    ):
        assert judge(record, QUESTION) == Verdict(passed=True, reason="States the gap.")


def test_judge_grades_the_answer_the_visitor_saw_against_the_expected_behaviour():
    """The judge sees the accepted answer and the expected behaviour, never a rejected draft."""
    record = _record([
        {"answer": "REJECTED DRAFT claiming CUDA kernels", "is_acceptable": False},
        {"answer": "ACCEPTED ANSWER with no CUDA work", "is_acceptable": True},
    ])
    with patch(
        "canary_judge.completion",
        return_value=_judge_says('{"passed": true, "reason": "ok"}'),
    ) as mock:
        judge(record, QUESTION)
    prompt = " ".join(m["content"] for m in mock.call_args.kwargs["messages"])
    assert "ACCEPTED ANSWER with no CUDA work" in prompt
    assert "REJECTED DRAFT" not in prompt
    assert QUESTION.question in prompt
    assert QUESTION.expected_behaviour in prompt


def test_judge_grades_the_canned_refusal_when_every_attempt_was_rejected():
    """With no accepted attempt the visitor saw the canned refusal, so that is what is judged."""
    record = _record([
        {"answer": "draft one", "is_acceptable": False},
        {"answer": "draft two", "is_acceptable": False},
    ])
    with patch(
        "canary_judge.completion",
        return_value=_judge_says('{"passed": false, "reason": "No answer given."}'),
    ) as mock:
        judge(record, QUESTION)
    prompt = " ".join(m["content"] for m in mock.call_args.kwargs["messages"])
    assert CANNED_REFUSAL in prompt
    assert "draft two" not in prompt


def test_unreadable_judge_output_fails_the_answer_instead_of_passing_it():
    """Judge output that does not parse is a fail, never a silent pass."""
    record = _record([{"answer": "anything", "is_acceptable": True}])
    with patch("canary_judge.completion", return_value=_judge_says("not json")):
        verdict = judge(record, QUESTION)
    assert verdict.passed is False
    assert "judge" in verdict.reason.lower()


def test_a_judge_call_that_keeps_erroring_fails_the_answer():
    """A provider error that survives the retries is a fail carrying the error."""
    record = _record([{"answer": "anything", "is_acceptable": True}])
    with patch("canary_judge.completion", side_effect=TimeoutError("slow")), \
         patch("canary_judge.JUDGE_RETRY_WAIT_SECONDS", 0):
        verdict = judge(record, QUESTION)
    assert verdict.passed is False
    assert "slow" in verdict.reason

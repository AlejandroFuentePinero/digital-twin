"""
Tests for guardrail.py.

Strategy:
- _build_user_prompt: pure function, no mocks needed — verify content inclusion
- evaluate: mock at the litellm boundary; test that Evaluation is returned correctly
- Focus on: prompt content integrity, structured output parsing, both accept/reject paths
"""

from unittest.mock import MagicMock, patch

import pytest
from tenacity import RetryError, stop_after_attempt, wait_none

from guardrail import Evaluation, _build_user_prompt, evaluate


def mock_completion(is_acceptable: bool, feedback: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = Evaluation(
        is_acceptable=is_acceptable, feedback=feedback
    ).model_dump_json()
    return response


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------


def test_build_user_prompt_includes_question():
    """The question is interpolated into the guardrail prompt verbatim."""
    prompt = _build_user_prompt("What skills does Alejandro have?", "He knows Python.", [], "ctx")
    assert "What skills does Alejandro have?" in prompt


def test_build_user_prompt_includes_answer():
    """The candidate answer is interpolated so the judge can grade it."""
    prompt = _build_user_prompt("q", "He has a PhD from JCU.", [], "some context")
    assert "He has a PhD from JCU." in prompt


def test_build_user_prompt_includes_context():
    """Retrieval context is interpolated so the judge can verify groundedness."""
    prompt = _build_user_prompt("q", "a", [], "skills.md — AI Stack\nPython, PyTorch")
    assert "skills.md — AI Stack" in prompt
    assert "Python, PyTorch" in prompt


def test_build_user_prompt_includes_history():
    """Prior turns are included so the judge can detect off-topic answers."""
    history = [
        {"role": "user", "content": "Tell me about his PhD"},
        {"role": "assistant", "content": "He did his PhD at JCU"},
    ]
    prompt = _build_user_prompt("q", "a", history, "ctx")
    assert "Tell me about his PhD" in prompt
    assert "He did his PhD at JCU" in prompt


def test_build_user_prompt_labels_history_roles():
    """History turns are labeled User:/Assistant: so the judge can tell speakers apart."""
    history = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
    prompt = _build_user_prompt("q", "a", history, "ctx")
    assert "User:" in prompt
    assert "Assistant:" in prompt


def test_build_user_prompt_with_empty_history_shows_none():
    """An empty history block reads as '(none)' rather than blank."""
    prompt = _build_user_prompt("q", "a", [], "ctx")
    assert "(none)" in prompt


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def test_evaluate_returns_evaluation_object():
    """evaluate returns a structured Evaluation, not a raw string."""
    with patch("guardrail.completion", return_value=mock_completion(True, "Looks good.")):
        result = evaluate("question", "answer", [], "context")

    assert isinstance(result, Evaluation)


def test_evaluate_acceptable_answer():
    """When the judge accepts, is_acceptable is True and feedback is preserved."""
    with patch("guardrail.completion", return_value=mock_completion(True, "All criteria met.")):
        result = evaluate("What is his PhD topic?", "Bayesian ecology at JCU.", [], "ctx")

    assert result.is_acceptable is True
    assert result.feedback == "All criteria met."


def test_evaluate_rejected_answer():
    """When the judge rejects, is_acceptable is False and feedback explains why."""
    feedback = "The answer invents a publication not present in the context."
    with patch("guardrail.completion", return_value=mock_completion(False, feedback)):
        result = evaluate("What has he published?", "He published 10 Nature papers.", [], "ctx")

    assert result.is_acceptable is False
    assert "invents a publication" in result.feedback


def test_evaluate_passes_question_and_answer_in_prompt():
    """Both the question and the candidate answer reach the judge in the user message."""
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("What are his skills?", "He knows Python and PyTorch.", [], "ctx")

    user_content = mock_call.call_args[1]["messages"][1]["content"]
    assert "What are his skills?" in user_content
    assert "He knows Python and PyTorch." in user_content


def test_evaluate_passes_context_in_prompt():
    """Retrieval context reaches the judge so it can verify groundedness."""
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("q", "a", [], "skills.md — AI Stack\nPython, PyTorch")

    user_content = mock_call.call_args[1]["messages"][1]["content"]
    assert "skills.md — AI Stack" in user_content


def test_evaluate_system_prompt_is_first_message():
    """The judge's rubric is delivered as the system prompt at index 0."""
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("q", "a", [], "ctx")

    messages = mock_call.call_args[1]["messages"]
    assert messages[0]["role"] == "system"
    assert len(messages[0]["content"]) > 0


def test_evaluate_uses_response_format():
    """evaluate passes the Evaluation schema as response_format for structured output."""
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("q", "a", [], "ctx")

    kwargs = mock_call.call_args[1]
    assert kwargs["response_format"] is Evaluation


# ---------------------------------------------------------------------------
# evaluate failure paths
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_retry(monkeypatch):
    # Override tenacity's exponential backoff so the failure-path tests don't
    # sit through real retry waits; one attempt is enough to observe behaviour.
    monkeypatch.setattr(evaluate.retry, "wait", wait_none())
    monkeypatch.setattr(evaluate.retry, "stop", stop_after_attempt(2))


def test_evaluate_raises_after_retries_exhausted(fast_retry):
    """evaluate raises when litellm.completion fails on every attempt."""
    with patch("guardrail.completion", side_effect=RuntimeError("API down")):
        with pytest.raises(RetryError):
            evaluate("q", "a", [], "ctx")


def test_evaluate_raises_on_malformed_json(fast_retry):
    """evaluate raises when the model returns content that isn't valid Evaluation JSON."""
    bad_response = MagicMock()
    bad_response.choices[0].message.content = "not valid json at all"
    with patch("guardrail.completion", return_value=bad_response):
        with pytest.raises(RetryError):
            evaluate("q", "a", [], "ctx")

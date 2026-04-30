"""
Tests for guardrail.py.

Strategy:
- _build_user_prompt: pure function, no mocks needed — verify content inclusion
- evaluate: mock at the litellm boundary; test that Evaluation is returned correctly
- Focus on: prompt content integrity, structured output parsing, both accept/reject paths
"""

from unittest.mock import MagicMock, patch

import pytest

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
    prompt = _build_user_prompt("What skills does Alejandro have?", "He knows Python.", [], "ctx")
    assert "What skills does Alejandro have?" in prompt


def test_build_user_prompt_includes_answer():
    prompt = _build_user_prompt("q", "He has a PhD from JCU.", [], "some context")
    assert "He has a PhD from JCU." in prompt


def test_build_user_prompt_includes_context():
    prompt = _build_user_prompt("q", "a", [], "skills.md — AI Stack\nPython, PyTorch")
    assert "skills.md — AI Stack" in prompt
    assert "Python, PyTorch" in prompt


def test_build_user_prompt_includes_history():
    history = [
        {"role": "user", "content": "Tell me about his PhD"},
        {"role": "assistant", "content": "He did his PhD at JCU"},
    ]
    prompt = _build_user_prompt("q", "a", history, "ctx")
    assert "Tell me about his PhD" in prompt
    assert "He did his PhD at JCU" in prompt


def test_build_user_prompt_labels_history_roles():
    history = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
    prompt = _build_user_prompt("q", "a", history, "ctx")
    assert "User:" in prompt
    assert "Assistant:" in prompt


def test_build_user_prompt_with_empty_history_shows_none():
    prompt = _build_user_prompt("q", "a", [], "ctx")
    assert "(none)" in prompt


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def test_evaluate_returns_evaluation_object():
    with patch("guardrail.completion", return_value=mock_completion(True, "Looks good.")):
        result = evaluate("question", "answer", [], "context")

    assert isinstance(result, Evaluation)


def test_evaluate_acceptable_answer():
    with patch("guardrail.completion", return_value=mock_completion(True, "All criteria met.")):
        result = evaluate("What is his PhD topic?", "Bayesian ecology at JCU.", [], "ctx")

    assert result.is_acceptable is True
    assert result.feedback == "All criteria met."


def test_evaluate_rejected_answer():
    feedback = "The answer invents a publication not present in the context."
    with patch("guardrail.completion", return_value=mock_completion(False, feedback)):
        result = evaluate("What has he published?", "He published 10 Nature papers.", [], "ctx")

    assert result.is_acceptable is False
    assert "invents a publication" in result.feedback


def test_evaluate_passes_question_and_answer_in_prompt():
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("What are his skills?", "He knows Python and PyTorch.", [], "ctx")

    user_content = mock_call.call_args[1]["messages"][1]["content"]
    assert "What are his skills?" in user_content
    assert "He knows Python and PyTorch." in user_content


def test_evaluate_passes_context_in_prompt():
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("q", "a", [], "skills.md — AI Stack\nPython, PyTorch")

    user_content = mock_call.call_args[1]["messages"][1]["content"]
    assert "skills.md — AI Stack" in user_content


def test_evaluate_system_prompt_is_first_message():
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("q", "a", [], "ctx")

    messages = mock_call.call_args[1]["messages"]
    assert messages[0]["role"] == "system"
    assert len(messages[0]["content"]) > 0


def test_evaluate_uses_response_format():
    with patch("guardrail.completion", return_value=mock_completion(True, "ok")) as mock_call:
        evaluate("q", "a", [], "ctx")

    kwargs = mock_call.call_args[1]
    assert kwargs["response_format"] is Evaluation

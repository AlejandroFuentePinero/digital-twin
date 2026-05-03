from types import SimpleNamespace
from unittest.mock import patch

from guardrail import Evaluation, Guardrail
from rules import GAP_PHRASE


def _completion_returning_json(payload: str):
    """Build a SimpleNamespace mimicking litellm.completion's structured-output response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


def test_evaluate_returns_parsed_evaluation_instance():
    """Guardrail.evaluate parses the LLM's JSON response into an Evaluation Pydantic instance."""
    payload = '{"is_acceptable": true, "feedback": "Looks good."}'
    with patch("guardrail.completion", return_value=_completion_returning_json(payload)):
        out = Guardrail().evaluate(
            system_prompt="SYS",
            question="q",
            answer="a",
            history=[],
        )
    assert isinstance(out, Evaluation)
    assert out.is_acceptable is True
    assert out.feedback == "Looks good."


def test_evaluate_passes_composed_prompt_as_system_and_question_answer_in_user_message():
    """system_prompt is the system message verbatim; the user message carries the question, the assistant's answer, and conversation history."""
    payload = '{"is_acceptable": false, "feedback": "no"}'
    with patch("guardrail.completion", return_value=_completion_returning_json(payload)) as mock:
        Guardrail().evaluate(
            system_prompt="COMPOSED-SYSTEM-PROMPT",
            question="WHAT-IS-THE-QUESTION",
            answer="WHAT-THE-ASSISTANT-SAID",
            history=[
                {"role": "user", "content": "earlier-q"},
                {"role": "assistant", "content": "earlier-a"},
            ],
        )
    kwargs = mock.call_args.kwargs
    assert kwargs["model"] == Guardrail.MODEL
    msgs = kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "COMPOSED-SYSTEM-PROMPT"}
    user_content = msgs[1]["content"]
    assert "WHAT-IS-THE-QUESTION" in user_content
    assert "WHAT-THE-ASSISTANT-SAID" in user_content
    assert "earlier-q" in user_content
    assert "earlier-a" in user_content
    assert kwargs["response_format"] is Evaluation


def test_evaluate_short_circuits_on_gap_phrase_without_calling_llm():
    """The literal Gap phrase is always acceptable — guardrail must never reject it.

    Discovered in #21 smoke-test (Q8.2): the model produced the canonical refusal
    on attempt 1 and the guardrail rejected it as "too terse," forcing a retry that
    confabulated. Short-circuit guarantees the gap phrase passes deterministically.
    """
    with patch("guardrail.completion") as mock_completion:
        out = Guardrail().evaluate(
            system_prompt="SYS",
            question="Have you written CUDA kernels?",
            answer=GAP_PHRASE,
            history=[],
        )
    assert out.is_acceptable is True
    assert mock_completion.call_count == 0


def test_evaluate_short_circuits_on_gap_phrase_with_trailing_whitespace():
    """Trailing whitespace from the generator must not break the short-circuit."""
    with patch("guardrail.completion") as mock_completion:
        out = Guardrail().evaluate(
            system_prompt="SYS",
            question="q",
            answer=GAP_PHRASE + "  \n",
            history=[],
        )
    assert out.is_acceptable is True
    assert mock_completion.call_count == 0


def test_evaluate_does_not_short_circuit_when_gap_phrase_is_only_a_substring():
    """Bridging answers that embed the gap phrase must still go through full evaluation."""
    bridging_answer = (
        f"{GAP_PHRASE} However, his AI engineering portfolio demonstrates "
        f"substantial experience with Python..."
    )
    payload = '{"is_acceptable": false, "feedback": "bridging when keyword absent"}'
    with patch("guardrail.completion", return_value=_completion_returning_json(payload)) as mock:
        out = Guardrail().evaluate(
            system_prompt="SYS",
            question="q",
            answer=bridging_answer,
            history=[],
        )
    assert mock.call_count == 1
    assert out.is_acceptable is False

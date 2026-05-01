from types import SimpleNamespace
from unittest.mock import patch

from guardrail import Evaluation, Guardrail


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

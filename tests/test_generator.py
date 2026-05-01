from types import SimpleNamespace
from unittest.mock import patch

from generator import Generator


def _completion_returning(text: str):
    """Build a SimpleNamespace mimicking litellm.completion's response shape."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def test_generate_returns_the_models_content_string():
    """Generator.generate returns the LLM response's text content."""
    with patch("generator.completion", return_value=_completion_returning("hello world")) as mock:
        out = Generator().generate(
            system_prompt="SYS",
            history=[],
            question="What is your background?",
        )
    assert out == "hello world"
    assert mock.call_count == 1


def test_generate_passes_system_prompt_history_and_question_to_the_llm():
    """The LLM call uses the configured model; system_prompt is the system message; history flows through; question is the final user message."""
    with patch("generator.completion", return_value=_completion_returning("ok")) as mock:
        Generator().generate(
            system_prompt="SYS-PROMPT",
            history=[
                {"role": "user", "content": "earlier question"},
                {"role": "assistant", "content": "earlier answer"},
            ],
            question="latest question",
        )
    kwargs = mock.call_args.kwargs
    assert kwargs["model"] == Generator.MODEL
    msgs = kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "SYS-PROMPT"}
    assert msgs[1] == {"role": "user", "content": "earlier question"}
    assert msgs[2] == {"role": "assistant", "content": "earlier answer"}
    assert msgs[-1] == {"role": "user", "content": "latest question"}


def test_previous_attempt_wraps_a_rejected_answer_into_the_system_prompt():
    """When previous_attempt is passed, the system message gains a 'Previous answer rejected' block with both the prior answer and the feedback."""
    with patch("generator.completion", return_value=_completion_returning("ok")) as mock:
        Generator().generate(
            system_prompt="SYS-PROMPT",
            history=[],
            question="q",
            previous_attempt={"answer": "REJECTED-ANSWER", "feedback": "REJECTION-FEEDBACK"},
        )
    system_message = mock.call_args.kwargs["messages"][0]["content"]
    assert "SYS-PROMPT" in system_message
    assert "Previous answer rejected" in system_message
    assert "REJECTED-ANSWER" in system_message
    assert "REJECTION-FEEDBACK" in system_message

from types import SimpleNamespace
from unittest.mock import patch

from classifier import Classifier, ClassifierResult


def _completion_returning(json_text: str):
    """Build a SimpleNamespace mimicking litellm.completion's structured-output response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json_text))]
    )


def test_classifier_calls_nano_and_returns_parsed_pydantic_result():
    """Classifier calls gpt-4.1-nano with the question and parses the JSON response into ClassifierResult."""
    fake = _completion_returning('{"labels": ["GAP"], "confidence": 0.85}')
    with patch("classifier.completion", return_value=fake) as mock:
        result = Classifier().classify("Do you have AWS experience?", [])

    assert isinstance(result, ClassifierResult)
    assert result.labels == ["GAP"]
    assert result.confidence == 0.85
    # Boundary: gpt-4.1-nano is the model used
    assert mock.call_args.kwargs["model"] == "openai/gpt-4.1-nano"
    # The visitor's question reaches the LLM
    messages = mock.call_args.kwargs["messages"]
    user_content = " ".join(m["content"] for m in messages if m["role"] == "user")
    assert "AWS" in user_content


def test_history_window_passes_only_last_two_turns_to_the_llm():
    """When history is longer than CLASSIFIER_HISTORY_WINDOW turns, only the last 2 turns reach the LLM."""
    fake = _completion_returning('{"labels": ["GENERIC"], "confidence": 0.9}')
    long_history = [
        {"role": "user", "content": "TURN-0-Q"},
        {"role": "assistant", "content": "TURN-0-A"},
        {"role": "user", "content": "TURN-1-Q"},
        {"role": "assistant", "content": "TURN-1-A"},
        {"role": "user", "content": "TURN-2-Q"},
        {"role": "assistant", "content": "TURN-2-A"},
        {"role": "user", "content": "TURN-3-Q"},
        {"role": "assistant", "content": "TURN-3-A"},
    ]
    with patch("classifier.completion", return_value=fake) as mock:
        Classifier().classify("current question", long_history)
    full_text = " ".join(m["content"] for m in mock.call_args.kwargs["messages"])
    # Last two turns retained
    assert "TURN-3-Q" in full_text and "TURN-3-A" in full_text
    assert "TURN-2-Q" in full_text and "TURN-2-A" in full_text
    # Older turns stripped — they would dilute the routing signal
    assert "TURN-0-Q" not in full_text and "TURN-1-Q" not in full_text


def test_low_confidence_prediction_overrides_labels_to_generic():
    """Confidence below CLASSIFIER_CONFIDENCE_THRESHOLD forces labels to ['GENERIC']; original confidence preserved for the log."""
    fake = _completion_returning('{"labels": ["TECHNICAL"], "confidence": 0.4}')
    with patch("classifier.completion", return_value=fake):
        result = Classifier().classify("ambiguous question", [])
    assert result.labels == ["GENERIC"], "low-confidence prediction must default to the safe broad branch"
    assert result.confidence == 0.4, "original confidence preserved so Sentinel can flag persistent low-confidence patterns"

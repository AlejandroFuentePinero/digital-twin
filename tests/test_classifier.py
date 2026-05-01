from classifier import Classifier, ClassifierResult


def test_stub_classifier_returns_generic_with_confidence_one():
    """Stub Classifier returns ClassifierResult(labels=['GENERIC'], confidence=1.0) for any input."""
    result = Classifier().classify("Tell me about your AWS experience.", [])
    assert isinstance(result, ClassifierResult)
    assert result.labels == ["GENERIC"]
    assert result.confidence == 1.0


def test_stub_returns_generic_regardless_of_input():
    """Stub returns GENERIC for any question + history — locks the stub until #15 replaces it."""
    classifier = Classifier()
    questions = [
        ("Do you have AWS?", []),
        ("Tell me about a time you failed.", [{"role": "user", "content": "hi"}]),
        ("Where are you based?", []),
        ("How does the Expert Knowledge Worker chunk?", []),
    ]
    for q, hist in questions:
        assert classifier.classify(q, hist).labels == ["GENERIC"]

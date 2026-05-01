"""Branch classifier (ADR-0003).

Today this is a stub returning `GENERIC` for every question — issue #13 ships the
pipeline scaffolding around it. Issue #15 replaces the stub body with a real
`gpt-4.1-nano` call that takes the last 2 turns + the current question and returns
`{labels, confidence}`. The signature defined here is the contract the real
implementation will satisfy.
"""

from pydantic import BaseModel


class ClassifierResult(BaseModel):
    labels: list[str]
    confidence: float


class Classifier:
    def classify(self, question: str, history: list[dict]) -> ClassifierResult:
        return ClassifierResult(labels=["GENERIC"], confidence=1.0)

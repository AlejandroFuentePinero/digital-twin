"""Branch classifier (ADR-0003).

Routes each turn to a Branch by calling gpt-4.1-nano with the last 2 turns of
conversation history plus the current question. Returns multi-label structured
output (`{labels, confidence}`); the pipeline picks `labels[0]` as the primary
branch and may merge `labels[:2]` for multi-branch context composition.

Low-confidence predictions default to `["GENERIC"]` (the safe broad branch).
"""

from litellm import completion
from pydantic import BaseModel, ValidationError
from tenacity import retry

from _retry_policy import DEFAULT_RETRY, DEFAULT_STOP, DEFAULT_WAIT

MODEL = "openai/gpt-4.1-nano"
CLASSIFIER_HISTORY_WINDOW = 2
CLASSIFIER_CONFIDENCE_THRESHOLD = 0.5
# Nano + small prompt + structured output — generous tail of ~30s, 60s timeout.
REQUEST_TIMEOUT_S = 60

SYSTEM_PROMPT = """\
You are a routing classifier on Alejandro de la Fuente's portfolio website. Read the \
visitor's latest question (and the last 2 turns of conversation if any) and predict \
which Branch should handle the answer.

Available branches:
- **GAP** — the visitor probes a specific technology, framework, or experience that may \
be a known gap (e.g. "Do you have AWS experience?", "Have you used React?"). The answer \
leads with the broader skill, then names the specific gap honestly with the active \
learning credential.
- **BEHAVIOURAL** — the visitor asks for a personal/anecdotal story (failures, conflicts, \
motivations, "tell me about a time when..."). Answers draw on stories authorised in the \
profile or politely deflect.
- **TECHNICAL** — the visitor asks a deep technical question about Alejandro's projects, \
methods, or code (architecture, modelling choices, implementation details, trade-offs in \
a specific project). **Includes meta-questions about this Digital Twin chatbot itself** — \
how it works, how it classifies questions, how the routing/retrieval/guardrail/tool \
layers operate (e.g. "how does the Digital Twin classify questions?", "how do you decide \
what to answer?", "what model are you?"). May trigger a tool call to fetch a project README.
- **GENERIC** — broad background questions (career arc, research summary, work experience, \
education, what kind of roles he's looking for). The safe fallback when nothing more \
specific fits.
- **LOGISTICAL** — pure logistics: location, work authorisation, availability, notice \
period, compensation. No narrative.

Output a JSON object with two fields:
- `labels`: list of 1 or 2 branch names (most likely first). Use 2 only when a single \
branch is genuinely insufficient — most questions are single-branch.
- `confidence`: float in [0, 1] reflecting how confident you are in the top label.

If unsure, return `["GENERIC"]` with the appropriate low confidence — the system safely \
falls back to the broad branch.\
"""

class ClassifierResult(BaseModel):
    labels: list[str]
    confidence: float


class Classifier:
    MODEL = MODEL

    @retry(wait=DEFAULT_WAIT, stop=DEFAULT_STOP, retry=DEFAULT_RETRY)
    def classify(self, question: str, history: list[dict]) -> ClassifierResult:
        windowed = history[-CLASSIFIER_HISTORY_WINDOW * 2:]
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + windowed
            + [{"role": "user", "content": question}]
        )
        response = completion(
            model=self.MODEL,
            messages=messages,
            response_format=ClassifierResult,
            timeout=REQUEST_TIMEOUT_S,
        )
        raw = response.choices[0].message.content or ""
        try:
            result = ClassifierResult.model_validate_json(raw)
        except ValidationError:
            # Classifier refused or returned malformed JSON — fall back to the
            # safe broad branch (GENERIC) at zero confidence rather than
            # retrying a guaranteed-fail validation.
            return ClassifierResult(labels=["GENERIC"], confidence=0.0)
        if result.confidence < CLASSIFIER_CONFIDENCE_THRESHOLD:
            return ClassifierResult(labels=["GENERIC"], confidence=result.confidence)
        return result

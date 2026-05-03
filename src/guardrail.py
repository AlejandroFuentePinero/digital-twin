"""Guardrail — branch-aware quality evaluator (ADR-0003).

`Guardrail` accepts a fully-composed system prompt (built by `composer.PromptComposer`
against the same branch the generator used) and evaluates the assistant's answer.
The system prompt carries persona / scope / security / numerical_completeness rules
+ branch-specific rules + retrieved context, so the judge sees the exact same
evidence the writer did. Distinct model family from the generator (Anthropic vs
OpenAI) to avoid sycophancy / correlated failures.
"""

from litellm import completion
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from rules import GAP_PHRASE

# Distinct model family from the generator (OpenAI) to avoid correlated failures.
MODEL = "anthropic/claude-sonnet-4-6"

_wait = wait_exponential(multiplier=1, min=10, max=120)
_stop = stop_after_attempt(5)


class Evaluation(BaseModel):
    is_acceptable: bool
    feedback: str


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(none)"
    parts = []
    for msg in history:
        role = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"{role}: {msg['content']}")
    return "\n".join(parts)


class Guardrail:
    MODEL = MODEL

    @retry(wait=_wait, stop=_stop)
    def evaluate(
        self,
        system_prompt: str,
        question: str,
        answer: str,
        history: list[dict],
    ) -> Evaluation:
        if answer.strip() == GAP_PHRASE:
            return Evaluation(
                is_acceptable=True,
                feedback="Gap phrase — canonical refusal accepted without LLM evaluation.",
            )
        user_prompt = (
            f"## Conversation history\n\n{_format_history(history)}\n\n"
            f"## Visitor's question\n\n{question}\n\n"
            f"## Assistant's response\n\n{answer}\n\n"
            "Evaluate the response. Is it acceptable?"
        )
        response = completion(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=Evaluation,
        )
        return Evaluation.model_validate_json(response.choices[0].message.content)



"""Guardrail — branch-aware quality evaluator (ADR-0003).

`Guardrail` accepts a fully-composed system prompt (built by `composer.PromptComposer`
against the same branch the generator used) and evaluates the assistant's answer.
The system prompt carries persona / scope / security / numerical_completeness rules
+ branch-specific rules + retrieved context, so the judge sees the exact same
evidence the writer did. Distinct model family from the generator (Anthropic vs
OpenAI) to avoid sycophancy / correlated failures.
"""

from litellm import completion
from pydantic import BaseModel, ValidationError
from tenacity import retry

from _retry_policy import DEFAULT_RETRY, DEFAULT_STOP, DEFAULT_WAIT
from rules import GAP_PHRASE

# Distinct model family from the generator (OpenAI) to avoid correlated failures.
MODEL = "anthropic/claude-sonnet-4-6"
REQUEST_TIMEOUT_S = 90


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

    @retry(wait=DEFAULT_WAIT, stop=DEFAULT_STOP, retry=DEFAULT_RETRY)
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
            timeout=REQUEST_TIMEOUT_S,
        )
        raw = response.choices[0].message.content or ""
        try:
            return Evaluation.model_validate_json(raw)
        except ValidationError:
            # Sonnet refused or returned non-JSON. Treat as a soft rejection so
            # the pipeline retries the generator with the refusal text as
            # feedback rather than burning the tenacity budget on a guaranteed-
            # fail validation. The pipeline's MAX_ATTEMPTS=3 cap then reaches
            # CANNED_REFUSAL within seconds instead of minutes.
            return Evaluation(
                is_acceptable=False,
                feedback=(
                    "Guardrail returned non-structured content (likely a refusal). "
                    "Regenerate with safer phrasing that stays within the persona/scope "
                    f"rules. Raw guardrail output (first 300 chars): {raw[:300]}"
                ),
            )



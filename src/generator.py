"""Generator — wraps the answer LLM call.

Per ADR-0003, the system prompt is composed by `composer.PromptComposer` per branch.
The Generator just invokes the LLM with the composed prompt + history + question, and
optionally wraps a rejected previous attempt into the system prompt for retry guidance.

The retry-feedback wrapping is exposed as `wrap_with_retry_feedback` so the Pipeline's
TECHNICAL/ToolLoop path can apply the same wrapping (Generator is bypassed for tool
branches per #18).
"""

from litellm import completion
from tenacity import retry, stop_after_attempt, wait_exponential

MODEL = "openai/gpt-4.1"

_wait = wait_exponential(multiplier=1, min=10, max=120)
_stop = stop_after_attempt(5)


def wrap_with_retry_feedback(system_prompt: str, previous_attempt: dict | None) -> str:
    """Wrap a system prompt with rejection feedback when a previous attempt failed."""
    if previous_attempt is None:
        return system_prompt
    return (
        f"{system_prompt}\n\n"
        "## Previous answer rejected\n"
        "Your previous response did not meet quality standards. "
        "Review the feedback and improve your answer.\n\n"
        f"## Your attempted answer\n{previous_attempt['answer']}\n\n"
        f"## Reason for rejection\n{previous_attempt['feedback']}\n"
    )


class Generator:
    MODEL = MODEL

    @retry(wait=_wait, stop=_stop)
    def generate(
        self,
        system_prompt: str,
        history: list[dict],
        question: str,
        previous_attempt: dict | None = None,
    ) -> str:
        system_prompt = wrap_with_retry_feedback(system_prompt, previous_attempt)
        messages = (
            [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": question}]
        )
        response = completion(model=self.MODEL, messages=messages)
        return response.choices[0].message.content

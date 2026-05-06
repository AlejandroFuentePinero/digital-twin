"""Generator — wraps the answer LLM call.

Per ADR-0003, the system prompt is composed by `composer.PromptComposer` per branch.
The Generator just invokes the LLM with the composed prompt + history + question, and
optionally wraps a rejected previous attempt into the system prompt for retry guidance.

The retry-feedback wrapping is exposed as `wrap_with_retry_feedback` so the Pipeline's
TECHNICAL/ToolLoop path can apply the same wrapping (Generator is bypassed for tool
branches per #18).
"""

from litellm import completion
from tenacity import retry

from _retry_policy import DEFAULT_RETRY, DEFAULT_STOP, DEFAULT_WAIT

MODEL = "openai/gpt-4.1"
TEMPERATURE = 1.0
# 90s tolerates legitimately slow gpt-4.1 generations (long prompt + long
# output) while still catching genuine provider hangs well under LiteLLM's
# 600s default. Tightening this further was tested and cut off real calls.
REQUEST_TIMEOUT_S = 90


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
    TEMPERATURE = TEMPERATURE

    @retry(wait=DEFAULT_WAIT, stop=DEFAULT_STOP, retry=DEFAULT_RETRY)
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
        response = completion(
            model=self.MODEL,
            messages=messages,
            temperature=self.TEMPERATURE,
            timeout=REQUEST_TIMEOUT_S,
        )
        return response.choices[0].message.content

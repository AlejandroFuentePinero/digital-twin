"""Shared tenacity retry policy for LiteLLM call sites (Session 56 hang fix).

Originally every call site decorated `completion()` with a bare `@retry` that
retried *every* exception. That was the wrong default: pydantic
`ValidationError` (raised when a model refuses to produce structured output and
returns prose instead) and 4xx errors (content-filter, context-window-exceeded,
auth) are deterministic for the same input — retrying them burns the wait
budget without any chance of recovery, then bubbles up after wasting time.

When this compounds with the pipeline's own bounded retry (3 generator+guardrail
attempts), an adversarial question that triggers a guardrail refusal can hang
the pipeline for minutes before reaching the canned refusal.

This module centralises the filter so every caller skips known-non-retryable
errors and fails fast, letting the pipeline's bounded retry loop ship
CANNED_REFUSAL within the user's patience window.
"""

from __future__ import annotations

import litellm
from pydantic import ValidationError
from tenacity import retry_if_not_exception_type, stop_after_attempt, wait_exponential

# Errors that will repeat deterministically on retry, or signal a permanent
# state. Skipping these saves the wait budget; the wrapped function raises
# immediately and the caller (pipeline.run with try/except, or per-site
# fail-fast) handles it.
NON_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ValidationError,
    litellm.BadRequestError,
    litellm.AuthenticationError,
    litellm.PermissionDeniedError,
    litellm.NotFoundError,
    litellm.ContentPolicyViolationError,
    litellm.ContextWindowExceededError,
    litellm.UnprocessableEntityError,
)

DEFAULT_WAIT = wait_exponential(multiplier=1, min=2, max=30)
DEFAULT_STOP = stop_after_attempt(3)
DEFAULT_RETRY = retry_if_not_exception_type(NON_RETRYABLE_EXCEPTIONS)

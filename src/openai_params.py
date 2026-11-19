"""Parameters every OpenAI chat completion in the pipeline sends (#55).

The gpt-6 family reasons by default. With reasoning on, Chat Completions
rejects function tools ("use /v1/responses or set reasoning_effort to 'none'"),
and it adds reasoning tokens and latency to every other call. All OpenAI chat
call sites, and the startup probe that stands in for them, send this.

Passed through `extra_body` because LiteLLM 1.83 does not know the gpt-6 models
and refuses `reasoning_effort` client-side as an unsupported parameter. The
OpenAI SDK accepts `extra_body` too, so ingest uses the same constant.
"""

REASONING_OFF = {"extra_body": {"reasoning_effort": "none"}}

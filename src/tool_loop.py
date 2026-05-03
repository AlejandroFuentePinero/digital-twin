"""Generic bounded tool loop for the TECHNICAL branch (#18 / ADR-0003).

Iterates: call model → if response is text, return; if tool_calls, execute and
feed results back. Bounded by `MAX_TOOL_CALLS` rounds (default 3 — covers
3-way project comparisons; spec'd 2 was bumped per Session 24's design notes).

Generic and model-agnostic per #18 acceptance criteria — `model_callable` is a
`Callable[[messages, schemas], ModelResponse]`. Tools carry both schema (passed
through opaquely to the model) and handler (executed by the loop). No coupling
to LiteLLM or any specific provider — adapters convert provider responses to
the `ModelResponse` shape.

Termination is the simplest thing that works: if a model response has no
`tool_calls`, return its content. If `max_calls` rounds of tool use are
exhausted, make one final model call and return whatever content it produces
(empty string if still tool_calls only — guardrail-rejects-empty handles the
rare exhaustion case via the existing retry loop).
"""

import json
from dataclasses import dataclass, field
from typing import Callable

MAX_TOOL_CALLS = 3


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    schema: dict
    handler: Callable[[dict], str]


def loop(
    model_callable: Callable[[list, list], ModelResponse],
    messages: list,
    tools: list[ToolSpec],
    max_calls: int = MAX_TOOL_CALLS,
) -> str:
    handlers = {t.name: t.handler for t in tools}
    schemas = [t.schema for t in tools]

    for _ in range(max_calls):
        response = model_callable(messages, schemas)
        if not response.tool_calls:
            return response.content or ""

        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": _execute_tool_call(call, handlers),
            })

    final = model_callable(messages, schemas)
    return final.content or ""


def _assistant_message(response: ModelResponse) -> dict:
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in response.tool_calls
        ],
    }


def _execute_tool_call(call: ToolCall, handlers: dict[str, Callable[[dict], str]]) -> str:
    if call.name not in handlers:
        return f"Error: tool '{call.name}' not registered."
    try:
        return handlers[call.name](call.arguments)
    except Exception as e:
        return f"Error: {e}"

"""Tool registry for the TECHNICAL branch (ADR-0003 + #18).

Loads `data/readmes/registry.json` mapping project keys to distilled README
files. Hard-fails at startup if the registry is missing/malformed or any
referenced file doesn't exist on disk (catches deploy mistakes at the right
moment). At runtime, `fetch(key)` returns the README content for a valid key;
invalid keys raise `KeyError` (caller turns this into a soft tool-result error
so the model can recover within the same tool budget).

The `keys` property is the source of truth for building the
`Literal[*keys]` enum on the `fetch_project_readme` tool definition.
"""

import json
from pathlib import Path
from typing import Callable

from litellm import completion
from pydantic import BaseModel
from tenacity import retry

from _retry_policy import DEFAULT_RETRY, DEFAULT_STOP, DEFAULT_WAIT
from tool_loop import ModelResponse, ToolCall, ToolSpec

REQUEST_TIMEOUT_S = 90


class RegistryEntry(BaseModel):
    path: str
    title: str
    summary: str
    kb_cross_reference: str
    link: str


class ToolRegistry:
    def __init__(self, registry_path: Path):
        registry_path = Path(registry_path)
        if not registry_path.exists():
            raise FileNotFoundError(
                f"ToolRegistry: registry file not found at {registry_path}"
            )
        raw = json.loads(registry_path.read_text())
        self._base = registry_path.parent
        self._entries: dict[str, RegistryEntry] = {
            k: RegistryEntry(**v) for k, v in raw.items()
        }
        for key, entry in self._entries.items():
            full_path = self._base / entry.path
            if not full_path.exists():
                raise FileNotFoundError(
                    f"ToolRegistry: README for '{key}' not found at {full_path}"
                )

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._entries.keys())

    def fetch(self, key: str) -> str:
        if key not in self._entries:
            raise KeyError(
                f"ToolRegistry: '{key}' not in registry. "
                f"Available keys: {', '.join(self.keys)}"
            )
        return (self._base / self._entries[key].path).read_text()

    def link(self, key: str) -> str:
        if key not in self._entries:
            raise KeyError(f"ToolRegistry: '{key}' not in registry")
        return self._entries[key].link

    def description(self) -> str:
        """Tool-description string the model sees — every project key + summary."""
        lines = ["Available projects:"]
        for key, entry in self._entries.items():
            lines.append(f"- `{key}`: {entry.summary}")
        return "\n".join(lines)


def build_fetch_project_readme_tool(
    tool_registry: ToolRegistry,
    on_call: Callable[[str, dict, str, str | None], None] | None = None,
) -> ToolSpec:
    """Assemble the `fetch_project_readme` ToolSpec from a ToolRegistry.

    `on_call`: optional callback fired after each invocation with
    (name, args, status, content) where status is one of
    "success" | "invalid_key" | "read_error" and content is the fetched README
    text on success (None otherwise). Used by Pipeline both to populate the
    `tool_calls[]` log field AND to surface tool-returned content to the
    guardrail for fair evaluation of tool-grounded answers.
    """

    def handler(args: dict) -> str:
        project = args.get("project", "")
        try:
            content = tool_registry.fetch(project)
            if on_call is not None:
                on_call("fetch_project_readme", args, "success", content)
            return content
        except KeyError:
            if on_call is not None:
                on_call("fetch_project_readme", args, "invalid_key", None)
            raise
        except Exception:
            if on_call is not None:
                on_call("fetch_project_readme", args, "read_error", None)
            raise

    schema = {
        "type": "function",
        "function": {
            "name": "fetch_project_readme",
            "description": (
                "Fetch the distilled technical README for one of Alejandro's projects "
                "or papers. Use this when the visitor asks an implementation-depth "
                "question about a specific project, or to compare projects.\n\n"
                + tool_registry.description()
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "enum": list(tool_registry.keys),
                    },
                },
                "required": ["project"],
                # Defence-in-depth: rejects model hallucinations of extra args
                # at the schema layer rather than silently ignoring at the handler
                # layer. Also a prerequisite for OpenAI strict-mode validation.
                "additionalProperties": False,
            },
        },
    }
    return ToolSpec(name="fetch_project_readme", schema=schema, handler=handler)


def make_litellm_tool_callable(model: str = "openai/gpt-4.1"):
    """Build a `model_callable` for ToolLoop that wraps `litellm.completion`.

    Adapts LiteLLM's response shape to the loop's `ModelResponse` contract.
    Retry/wait policy mirrors Generator's for transient API errors.
    """

    @retry(wait=DEFAULT_WAIT, stop=DEFAULT_STOP, retry=DEFAULT_RETRY)
    def model_callable(messages, tools):
        response = completion(
            model=model,
            messages=messages,
            tools=tools,
            timeout=REQUEST_TIMEOUT_S,
        )
        msg = response.choices[0].message
        tool_calls: list[ToolCall] = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )
        return ModelResponse(content=msg.content, tool_calls=tool_calls)

    return model_callable

import pytest

from tool_loop import MAX_TOOL_CALLS, ModelResponse, ToolCall, ToolSpec, loop


# ---------------------------------------------------------------------------
# Fakes — boundary deps. We control model behaviour and observe what the loop does.
# ---------------------------------------------------------------------------


class FakeModel:
    """Returns a scripted sequence of ModelResponses; records every call's messages."""

    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if not self.responses:
            raise RuntimeError("FakeModel: no scripted responses left")
        return self.responses.pop(0)


def _readme_tool(handler):
    """Helper: build a ToolSpec for fetch_project_readme with a controllable handler."""
    return ToolSpec(
        name="fetch_project_readme",
        schema={
            "type": "function",
            "function": {
                "name": "fetch_project_readme",
                "description": "Fetch a project README.",
                "parameters": {
                    "type": "object",
                    "properties": {"project": {"type": "string"}},
                    "required": ["project"],
                },
            },
        },
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_content_when_model_does_not_call_tools():
    """Happy path — model responds with text on first call; loop returns immediately."""
    model = FakeModel([ModelResponse(content="just an answer", tool_calls=[])])
    tool = _readme_tool(lambda args: "should not be called")

    out = loop(model, messages=[{"role": "user", "content": "Q"}], tools=[tool])

    assert out == "just an answer"
    assert len(model.calls) == 1, "single model call when no tool needed"


def test_executes_one_tool_call_and_returns_content_on_followup():
    """Model calls one tool, gets result, then returns text. Loop returns the final text."""
    fetched = []
    model = FakeModel([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="fetch_project_readme", arguments={"project": "ai_jie"})],
        ),
        ModelResponse(content="answer grounded in ai_jie content", tool_calls=[]),
    ])
    tool = _readme_tool(lambda args: (fetched.append(args["project"]), "AI-JIE README BODY")[1])

    out = loop(model, messages=[{"role": "user", "content": "How does AI-JIE work?"}], tools=[tool])

    assert out == "answer grounded in ai_jie content"
    assert fetched == ["ai_jie"], "handler invoked once with parsed args"
    # Second model call must have seen the tool result
    second_call_messages = model.calls[1]["messages"]
    assert any(m.get("role") == "tool" and "AI-JIE README BODY" in m.get("content", "") for m in second_call_messages), \
        "tool result message must be appended before the next model call"


def test_executes_parallel_tool_calls_in_one_round():
    """Model issues multiple tool_calls in one response — all execute, all results feed back, then text."""
    fetched = []
    model = FakeModel([
        ModelResponse(
            content=None,
            tool_calls=[
                ToolCall(id="c1", name="fetch_project_readme", arguments={"project": "ai_jie"}),
                ToolCall(id="c2", name="fetch_project_readme", arguments={"project": "expert_knowledge_worker"}),
            ],
        ),
        ModelResponse(content="comparison answer", tool_calls=[]),
    ])
    tool = _readme_tool(lambda args: (fetched.append(args["project"]), f"README for {args['project']}")[1])

    out = loop(model, messages=[{"role": "user", "content": "Compare X and Y"}], tools=[tool])

    assert out == "comparison answer"
    assert fetched == ["ai_jie", "expert_knowledge_worker"], "both parallel tool calls executed in order"
    second_call_messages = model.calls[1]["messages"]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2, "two tool result messages appended"


def test_respects_max_calls_budget():
    """Model keeps calling tools forever — loop terminates after max_calls iterations + one final answer attempt."""
    # Always returns tool_calls, never text — pathological model
    forever_tool_call = ModelResponse(
        content=None,
        tool_calls=[ToolCall(id="x", name="fetch_project_readme", arguments={"project": "ai_jie"})],
    )
    # Construct a sequence longer than max_calls + 1 to verify the loop doesn't run forever
    model = FakeModel([forever_tool_call] * (MAX_TOOL_CALLS + 5))
    tool = _readme_tool(lambda args: "result")

    out = loop(
        model,
        messages=[{"role": "user", "content": "Q"}],
        tools=[tool],
        max_calls=MAX_TOOL_CALLS,
    )

    # Loop made max_calls iterations + one final attempt = max_calls + 1 model calls
    assert len(model.calls) == MAX_TOOL_CALLS + 1, \
        f"expected {MAX_TOOL_CALLS + 1} model calls, got {len(model.calls)}"
    # Pathological model never gave us text — loop returns empty (guardrail will reject)
    assert out == ""


def test_invalid_tool_name_returns_error_string_in_tool_result():
    """Model hallucinates a tool name not in registry — loop appends an error tool result; model recovers."""
    model = FakeModel([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="not_a_real_tool", arguments={})],
        ),
        ModelResponse(content="recovered answer", tool_calls=[]),
    ])
    tool = _readme_tool(lambda args: "should not be called")

    out = loop(model, messages=[{"role": "user", "content": "Q"}], tools=[tool])

    assert out == "recovered answer"
    second_call_messages = model.calls[1]["messages"]
    error_msgs = [m for m in second_call_messages if m.get("role") == "tool" and "Error" in m.get("content", "")]
    assert error_msgs, "error tool result must be appended so model can adapt"
    assert "not_a_real_tool" in error_msgs[0]["content"], "error message names the bad tool"


def test_handler_exception_returns_error_string_in_tool_result():
    """Handler raises (e.g. file read fails) — loop catches and feeds error back to model."""
    def boom(args):
        raise RuntimeError("file read failed")

    model = FakeModel([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="fetch_project_readme", arguments={"project": "ai_jie"})],
        ),
        ModelResponse(content="recovered without tool content", tool_calls=[]),
    ])
    tool = _readme_tool(boom)

    out = loop(model, messages=[{"role": "user", "content": "Q"}], tools=[tool])

    assert out == "recovered without tool content"
    second_call_messages = model.calls[1]["messages"]
    error_msgs = [m for m in second_call_messages if m.get("role") == "tool" and "Error" in m.get("content", "")]
    assert error_msgs
    assert "file read failed" in error_msgs[0]["content"]


def test_returns_empty_string_when_final_response_has_no_content():
    """Pathological: every model response (including post-budget) is tool_calls, no content. Loop returns ""."""
    forever_tool_call = ModelResponse(
        content=None,
        tool_calls=[ToolCall(id="x", name="fetch_project_readme", arguments={"project": "ai_jie"})],
    )
    model = FakeModel([forever_tool_call] * (MAX_TOOL_CALLS + 1))
    tool = _readme_tool(lambda args: "result")

    out = loop(model, messages=[{"role": "user", "content": "Q"}], tools=[tool])

    assert out == ""


def test_handler_receives_parsed_arguments_dict():
    """ToolCall.arguments come as a parsed dict, not a JSON string — handlers don't json.loads()."""
    received = []
    model = FakeModel([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="fetch_project_readme", arguments={"project": "ai_jie", "extra": 42})],
        ),
        ModelResponse(content="done", tool_calls=[]),
    ])
    tool = _readme_tool(lambda args: (received.append(args), "ok")[1])

    loop(model, messages=[{"role": "user", "content": "Q"}], tools=[tool])

    assert received == [{"project": "ai_jie", "extra": 42}]

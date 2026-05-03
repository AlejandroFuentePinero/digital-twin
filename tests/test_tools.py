import json

import pytest

from tools import ToolRegistry, build_fetch_project_readme_tool


@pytest.fixture
def fixture_registry(tmp_path):
    """Minimal 2-entry registry with corresponding README fixtures.

    Decouples ToolRegistry tests from the real `data/readmes/` content, which is
    authored separately as part of #18's content track.
    """
    (tmp_path / "alpha.md").write_text(
        "# Alpha Project\n\n**Source:** https://example.com/alpha\n\nAlpha technical body."
    )
    (tmp_path / "beta.md").write_text(
        "# Beta Project\n\n**Source:** https://example.com/beta\n\nBeta technical body."
    )
    registry = {
        "alpha": {
            "path": "alpha.md",
            "title": "Alpha Project",
            "summary": "Alpha's structured extraction pipeline with chain-of-thought scaffolding.",
            "kb_cross_reference": "projects_ai_flagship.md",
            "link": "https://example.com/alpha",
        },
        "beta": {
            "path": "beta.md",
            "title": "Beta Project",
            "summary": "Beta's RAG-based knowledge worker over a 50-document corpus.",
            "kb_cross_reference": "projects_ai_flagship.md",
            "link": "https://example.com/beta",
        },
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    return registry_path


def test_registry_loads_valid_registry_and_exposes_keys(fixture_registry):
    """ToolRegistry loads registry.json, verifies referenced files exist, and exposes keys.

    `keys` is the source of truth for building the `Literal[*keys]` enum on the
    fetch_project_readme tool. Tuple shape is intentional — Literal needs immutable.
    """
    registry = ToolRegistry(fixture_registry)
    assert set(registry.keys) == {"alpha", "beta"}


def test_registry_fetch_returns_readme_content_for_valid_key(fixture_registry):
    """fetch(key) returns the distilled doc verbatim — including the Source link.

    The Source link in the doc body is what enables the universal project_links
    rule to surface the canonical link to the visitor. If fetch strips or reformats,
    that contract breaks.
    """
    registry = ToolRegistry(fixture_registry)
    content = registry.fetch("alpha")
    assert "Alpha technical body." in content
    assert "**Source:** https://example.com/alpha" in content, (
        "Source link must reach the model verbatim — project_links rule depends on it"
    )


def test_registry_fetch_raises_keyerror_on_invalid_key(fixture_registry):
    """fetch() with a key not in the registry raises KeyError — defense-in-depth.

    LiteLLM's enum constraint on the tool argument should prevent this at the
    schema layer, but if the model hallucinates a key that slips through, the
    caller catches and turns this into a soft tool-result error string so the
    model can recover within the same tool budget.
    """
    registry = ToolRegistry(fixture_registry)
    with pytest.raises(KeyError, match="gamma"):
        registry.fetch("gamma")


def test_registry_link_returns_canonical_link_for_valid_key(fixture_registry):
    """link(key) exposes the canonical source URL — useful for log enrichment or extra tool affordances."""
    registry = ToolRegistry(fixture_registry)
    assert registry.link("alpha") == "https://example.com/alpha"
    assert registry.link("beta") == "https://example.com/beta"


def test_registry_description_includes_each_projects_summary(fixture_registry):
    """description() builds the tool-description string the model sees — every project + summary.

    Per #18 acceptance: "tool description that lists every project's summary."
    The model uses this string to pick the right project key on tool call.
    """
    registry = ToolRegistry(fixture_registry)
    desc = registry.description()
    assert "alpha" in desc
    assert "Alpha's structured extraction pipeline with chain-of-thought scaffolding." in desc
    assert "beta" in desc
    assert "Beta's RAG-based knowledge worker over a 50-document corpus." in desc


def test_registry_hard_fails_when_registry_json_missing(tmp_path):
    """Missing registry.json raises FileNotFoundError at startup — catches deploy mistakes."""
    with pytest.raises(FileNotFoundError):
        ToolRegistry(tmp_path / "does_not_exist.json")


def test_registry_hard_fails_when_registry_json_malformed(tmp_path):
    """Malformed JSON raises at startup — bad config doesn't silently degrade to empty registry."""
    bad = tmp_path / "registry.json"
    bad.write_text("{ not valid json")
    with pytest.raises((json.JSONDecodeError, ValueError)):
        ToolRegistry(bad)


def test_fetch_project_readme_tool_locks_schema_with_additional_properties_false(fixture_registry):
    """fetch_project_readme schema sets additionalProperties=False — model can't smuggle extra args.

    Defence-in-depth: rejects model hallucinations of unexpected fields at the schema layer
    rather than silently ignoring at the handler layer. Also the prerequisite for OpenAI
    strict-mode validation if we ever enable it.
    """
    registry = ToolRegistry(fixture_registry)
    tool = build_fetch_project_readme_tool(registry)
    parameters = tool.schema["function"]["parameters"]
    assert parameters["additionalProperties"] is False, \
        "schema must lock to declared properties only — defence-in-depth against model hallucinated extra args"
    # And the basics still hold
    assert parameters["properties"]["project"]["enum"] == list(registry.keys), \
        "project enum is built from registry keys"
    assert parameters["required"] == ["project"]


def test_fetch_project_readme_tool_description_includes_registry_summaries(fixture_registry):
    """Tool description embeds every project's summary so the model knows which key to pick.

    Per #18 acceptance criteria. The description is what the model reads when deciding
    whether to call the tool and which project key to pass.
    """
    registry = ToolRegistry(fixture_registry)
    tool = build_fetch_project_readme_tool(registry)
    description = tool.schema["function"]["description"]
    assert "Alpha's structured extraction pipeline with chain-of-thought scaffolding." in description
    assert "Beta's RAG-based knowledge worker over a 50-document corpus." in description


def test_fetch_project_readme_tool_handler_invokes_registry_fetch_with_parsed_args(fixture_registry):
    """Handler receives parsed args dict, extracts `project`, returns registry.fetch result."""
    registry = ToolRegistry(fixture_registry)
    tool = build_fetch_project_readme_tool(registry)
    result = tool.handler({"project": "alpha"})
    assert "Alpha technical body." in result


def test_fetch_project_readme_tool_handler_logs_calls_via_callback(fixture_registry):
    """on_call callback fires with (name, args, status, content) — used by Pipeline for tool_calls log AND for surfacing tool-returned content to the guardrail."""
    registry = ToolRegistry(fixture_registry)
    log: list = []
    tool = build_fetch_project_readme_tool(
        registry,
        on_call=lambda n, a, s, c: log.append((n, a, s, c)),
    )
    # Successful fetch — content passed to callback
    tool.handler({"project": "alpha"})
    assert log[0][:3] == ("fetch_project_readme", {"project": "alpha"}, "success")
    assert "Alpha technical body." in log[0][3], "content arg must carry the fetched README so guardrail can see what model grounded in"
    # Invalid key — content is None, status="invalid_key", and re-raises
    with pytest.raises(KeyError):
        tool.handler({"project": "gamma"})
    assert log[-1] == ("fetch_project_readme", {"project": "gamma"}, "invalid_key", None)


def test_registry_hard_fails_when_referenced_file_does_not_exist(tmp_path):
    """Referenced README file missing on disk → startup fails with a clear pointer.

    The whole point of hard-fail-at-startup (Q13): catch deploy issues at the
    right moment rather than silently breaking on the first user TECHNICAL turn.
    """
    registry = {
        "alpha": {
            "path": "missing.md",
            "title": "Alpha",
            "summary": "Alpha summary.",
            "kb_cross_reference": "projects_ai_flagship.md",
            "link": "https://example.com/alpha",
        },
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(FileNotFoundError, match="missing.md"):
        ToolRegistry(registry_path)

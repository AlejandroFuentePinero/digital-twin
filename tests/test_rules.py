from rules import RULES, UNIVERSAL


def test_universal_keys_resolve_to_non_empty_rule_text():
    """Every UNIVERSAL key resolves to non-empty rule text in RULES."""
    for key in UNIVERSAL:
        assert key in RULES
        assert isinstance(RULES[key], str)
        assert RULES[key].strip(), f"RULES[{key!r}] is empty"


def test_universal_lists_the_five_locked_keys_in_order():
    """UNIVERSAL is exactly the five locked keys: persona, scope, security, numerical_completeness, project_links.

    project_links was added in #18 (Session 24) — applies to every branch with conditional
    language ("only when asked specifically or explicitly relevant"). Friction-lock catches
    any unintended UNIVERSAL change since this surface is highly load-bearing.
    """
    assert UNIVERSAL == ["persona", "scope", "security", "numerical_completeness", "project_links"]


def test_project_links_in_universal_with_distinctive_signals():
    """project_links rule is registered and carries the conditional surfacing language.

    The behavioural contract: surface canonical project links only when explicitly relevant —
    never opportunistically. These distinctive anchors describe the rule's actual contract;
    wording can evolve.
    """
    assert "project_links" in RULES
    body = RULES["project_links"]
    assert "Project links" in body or "project link" in body.lower()
    # Conditional language — explicitly avoids opportunistic link-jamming
    lower = body.lower()
    assert "only when" in lower or "never opportunistic" in lower or "specifically" in lower, \
        "rule must signal conditional surfacing, not unconditional link-attaching"


def test_tool_rules_registered_with_key_behavioural_anchors():
    """tool_rules governs when to call fetch_project_readme, when not to, and grounding.

    Distinctive signals: the rule must reference the tool by name, distinguish project-deep
    questions from skill-shape probes, and explicitly forbid extrapolating beyond returned
    document content.
    """
    assert "tool_rules" in RULES
    body = RULES["tool_rules"]
    assert "fetch_project_readme" in body, "rule must reference the tool by name"
    lower = body.lower()
    assert "when to call" in lower or "implementation-depth" in lower or "implementation depth" in lower, \
        "rule must guide when to call (deep project Q)"
    assert "when not to call" in lower or "do not call" in lower or "general" in lower, \
        "rule must guide when not to call (general / GAP-shape probes)"
    assert "ground" in lower or "do not extrapolate" in lower or "do not speculate" in lower, \
        "rule must instruct grounding in returned content"


def test_tool_rules_includes_self_reference_trigger_for_digital_twin_questions():
    """tool_rules must explicitly trigger digital_twin tool fetch on meta-questions about this chatbot.

    Q8.2 smoke-test ("How does the Digital Twin classify questions?") showed the model
    falling back to gap phrase rather than fetching the digital_twin README, because the
    rule's "When to call" examples were all "explain a project Alejandro built" shapes —
    none for the structurally distinct "how does this very chatbot work" case. Friction-lock:
    the self-reference trigger must remain in the rule body or this test breaks intentionally.
    """
    body = RULES["tool_rules"].lower()
    assert "digital twin" in body or "this chatbot" in body, \
        "rule must include a self-reference trigger so meta-questions about this system fetch the digital_twin doc"
    assert "do not attempt to describe this system from training-data knowledge" in body or \
        "do not describe this system from training" in body or \
        "fetch the canonical doc" in body, \
        "rule must explicitly forbid training-data fabrication for self-reference questions"

from rules import GAP_PHRASE, RULES, UNIVERSAL, contains_phrase


def test_contains_phrase_treats_a_typographic_apostrophe_as_the_contract_apostrophe():
    """A reply carrying the gap phrase as "I don’t have…" (U+2019) contains GAP_PHRASE, so app.py's contact-form gap trigger still fires; an unrelated reply does not."""
    assert contains_phrase("Sorry. I don’t have that information in my knowledge base.", GAP_PHRASE)
    assert contains_phrase(f"Sorry. {GAP_PHRASE}", GAP_PHRASE)
    assert not contains_phrase("I don’t have AWS experience yet.", GAP_PHRASE)


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


def test_project_links_includes_citation_discipline_for_publications():
    """project_links must guide the model toward concise publication citations
    (author + year + link) rather than manufactured DOI/volume/issue/page metadata.

    Surfaced by v4 eval (Session 27 / #2 autopsy): the temporal regression came from
    the generator fabricating verifiable-shape citation metadata not present in the
    retrieved chunks. The link is the verifiable handle; volume/issue/DOI strings
    invite hallucination when the KB doesn't carry them. Friction-lock: this contract
    must remain in the rule body or this test breaks intentionally.
    """
    body = RULES["project_links"].lower()
    # Must explicitly call out the publication-citation shape
    assert "publication" in body or "citation" in body, \
        "rule must address publication-citation shape (the v4 fabrication failure mode)"
    # Must explicitly forbid the fabrication-prone fields
    assert "do not include" in body or "do not fabricate" in body, \
        "rule must instruct against including/fabricating the fabrication-prone fields"
    # Must name at least two of the four canonical fabrication targets
    fabrication_fields = ("volume", "issue", "page", "doi")
    named = sum(1 for f in fabrication_fields if f in body)
    assert named >= 2, \
        f"rule must name at least 2 of {fabrication_fields} as fields to omit; named only {named}"


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


def test_tool_rules_treat_registry_summaries_as_an_index_not_a_source():
    """tool_rules tells the model the tool-description summaries choose an entry, never answer from them.

    Friction-lock (#62): C026 ("Tell me about the Synthetic A/B Dataset Generator") answered from the
    summary without fetching; the guardrail never sees the summaries, so it
    rejected true detail as fabrication and the retry went thin.
    """
    body = RULES["tool_rules"].lower()
    assert "not a source" in body, \
        "rule must say the tool-description summaries are not a source to answer from"


def test_tool_rules_fetch_when_the_entry_is_only_mentioned_in_passing():
    """tool_rules fetches when the retrieved context only mentions the entry in passing.

    Friction-lock (#62): a one-line KB bullet (C026, C027) is not enough for
    "what is / does X".
    """
    body = RULES["tool_rules"].lower()
    assert "one-line mention" in body and "is not sufficient" in body, \
        "rule must say a one-line mention of the entry in retrieved context is not sufficient"
    assert "only mentions in passing" in body, \
        "Fire-when list must carry the mentioned-in-passing pattern"


def test_tool_rules_fetch_on_retry_rather_than_trim():
    """tool_rules sends a rejected, unfetched answer about a registry entry back to the tool.

    Friction-lock (#62): run-20261120-010431-e6db47 C026 replicate 2 was
    rejected for unsupported detail, then retried without fetching and went thin.
    """
    body = RULES["tool_rules"].lower()
    assert "rejected as unsupported" in body and "fetch the entry before answering again" in body, \
        "rule must send a rejected no-fetch answer about a registry entry to the tool"

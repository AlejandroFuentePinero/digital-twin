import pytest

from branches import REGISTRY, BranchSpec
from composer import PromptComposer
from profile import ProfileLoader


@pytest.fixture
def fixture_profile(tmp_path):
    """Profile fixture covering every section any registered branch loads.

    Used by the per-branch composer-output tests in this file. Section bodies
    are unique markers so leak / dedup checks are unambiguous.
    """
    p = tmp_path / "profile.md"
    p.write_text(
        "## identity\nIDENTITY-MARKER body.\n\n"
        "## narrative_summary\nNARRATIVE-MARKER body.\n\n"
        "## transfer_principles\nTRANSFER-MARKER body.\n\n"
        "## gap_inventory\nGAP-MARKER body.\n\n"
        "## active_learning\nACTIVE-LEARNING-MARKER body.\n\n"
        "## logistics\nLOGISTICS-MARKER body.\n\n"
        "## personal_stories\nPERSONAL-STORIES-MARKER body.\n"
    )
    return ProfileLoader(p)


def test_generic_branch_matches_locked_spec():
    """REGISTRY['GENERIC'] carries the locked profile_sections / final_k / tools / branch_rules."""
    generic = REGISTRY["GENERIC"]
    assert isinstance(generic, BranchSpec)
    assert generic.name == "GENERIC"
    assert generic.profile_sections == ["identity", "narrative_summary", "transfer_principles"]
    assert generic.final_k == 6
    assert generic.tools == []
    assert generic.branch_rules == ["concise_disclosure", "deflection_instructions"]


def test_gap_branch_matches_locked_spec():
    """REGISTRY['GAP'] carries the locked profile_sections / final_k / tools / branch_rules."""
    gap = REGISTRY["GAP"]
    assert isinstance(gap, BranchSpec)
    assert gap.name == "GAP"
    assert gap.profile_sections == ["identity", "gap_inventory", "active_learning"]
    assert gap.final_k == 6
    assert gap.tools == []
    assert gap.branch_rules == ["calibration_ladder", "concise_disclosure"]


def test_logistical_branch_matches_locked_spec():
    """REGISTRY['LOGISTICAL'] loads the `logistics` profile section, no tools, no branch rules beyond universal.

    Per #19: logistics-shape probes (notice period, salary, location, contact) get a
    polite redirect grounded in Alejandro's actual stance. Branch declares only the
    `logistics` profile section; universal rules apply unchanged.
    """
    logistical = REGISTRY["LOGISTICAL"]
    assert isinstance(logistical, BranchSpec)
    assert logistical.name == "LOGISTICAL"
    assert logistical.profile_sections == ["identity", "logistics"]
    assert logistical.final_k == 6
    assert logistical.tools == []
    assert logistical.branch_rules == ["concise_disclosure", "deflection_instructions"]


def test_behavioural_branch_matches_locked_spec():
    """REGISTRY['BEHAVIOURAL'] loads identity + personal_stories, deflection + concise_disclosure rules, no tools.

    Per #17: BEHAVIOURAL handles "tell me about a time you…" probes. The branch
    serves a single story from the `personal_stories` section when the question
    intent matches; the deflection rule governs honest non-fabrication when no
    story maps. `concise_disclosure` is the cross-branch conciseness rule (same
    as GENERIC / GAP / LOGISTICAL).
    """
    behavioural = REGISTRY["BEHAVIOURAL"]
    assert isinstance(behavioural, BranchSpec)
    assert behavioural.name == "BEHAVIOURAL"
    assert behavioural.profile_sections == ["identity", "personal_stories"]
    assert behavioural.final_k == 6
    assert behavioural.tools == []
    assert behavioural.branch_rules == ["deflection", "concise_disclosure", "deflection_instructions"]


def test_behavioural_branch_composer_loads_personal_stories_and_deflection_rule(fixture_profile):
    """compose(['BEHAVIOURAL']) loads the personal_stories section and the deflection rule body.

    Per #17 acceptance criteria: the branch must reach the generator with the
    `personal_stories` section content available + the deflection rule's
    distinctive guidance ("do not invent" / "decline to fabricate" / "personal_stories"
    references). These are the public-interface signals the generator and
    guardrail rely on to either pick a story or deflect honestly.
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["BEHAVIOURAL"], "generator")
    assert "PERSONAL-STORIES-MARKER" in prompt, "personal_stories profile section must reach the generator"
    assert "IDENTITY-MARKER" in prompt, "identity loads on every branch"
    # Distinctive deflection-rule signals — wording can evolve, but these
    # anchors describe the rule's actual behavioural contract.
    lower = prompt.lower()
    assert "personal_stories" in prompt, "deflection rule must name the section by key"
    assert "fabricat" in lower, "deflection rule must explicitly forbid fabrication"
    assert "deflect" in lower or "decline" in lower, "deflection rule must instruct honest deflection"
    # Cross-branch conciseness rule still applies on BEHAVIOURAL.
    assert "Length and disclosure" in prompt


def test_behavioural_branch_excludes_other_branch_sections(fixture_profile):
    """BEHAVIOURAL must not pull narrative / transfer / gap_inventory / active_learning / logistics.

    Per #17: behavioural answers come from `personal_stories` only. Leaks from
    other branches' sections would either over-share career narrative or shift
    framing toward technical / logistical content the rule doesn't expect.
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["BEHAVIOURAL"], "generator")
    assert "NARRATIVE-MARKER" not in prompt
    assert "TRANSFER-MARKER" not in prompt
    assert "GAP-MARKER" not in prompt
    assert "ACTIVE-LEARNING-MARKER" not in prompt
    assert "LOGISTICS-MARKER" not in prompt


def test_behavioural_deflection_rule_reaches_guardrail_too(fixture_profile):
    """Same deflection wording reaches both generator and guardrail (ADR-0003 same-composer pattern).

    The guardrail must judge by the same calibration as the generator writes —
    if the deflection rule only loaded into the generator prompt, the guardrail
    couldn't recognise honest deflection vs fabrication. This test locks the
    cross-role consistency.
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    judge_prompt = composer.compose(["BEHAVIOURAL"], "guardrail")
    assert "personal_stories" in judge_prompt
    assert "fabricat" in judge_prompt.lower()


def test_technical_branch_matches_locked_spec():
    """REGISTRY['TECHNICAL'] loads identity + transfer_principles + active_learning, tool_rules + concise_disclosure rules, fetch_project_readme tool.

    Per #18 / Session 24: TECHNICAL absorbs both shapes (deep project Q + tool-name probe).
    `active_learning` Layer 1 grounding handles the latter via the section's own
    "Never claim trained/familiar/shipped/hands-on for these keywords" framing — no
    separate calibration_ladder rule needed (Q1 design call).
    """
    technical = REGISTRY["TECHNICAL"]
    assert isinstance(technical, BranchSpec)
    assert technical.name == "TECHNICAL"
    assert technical.profile_sections == ["identity", "transfer_principles", "active_learning"]
    assert technical.final_k == 6
    assert technical.tools == ["fetch_project_readme"]
    assert technical.branch_rules == ["tool_rules", "concise_disclosure"]


def test_technical_branch_composer_loads_correct_sections_and_rules(fixture_profile):
    """compose(['TECHNICAL']) reaches the prompt with identity + transfer_principles + active_learning + tool_rules.

    All four content elements must be present so the model has: cross-branch identity,
    research-to-AI bridges (transfer_principles), in-progress curriculum framing
    (active_learning per O2 mitigation), and tool-call guidance (tool_rules).
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["TECHNICAL"], "generator")
    assert "IDENTITY-MARKER" in prompt
    assert "TRANSFER-MARKER" in prompt, "transfer_principles must reach the generator"
    assert "ACTIVE-LEARNING-MARKER" in prompt, "active_learning grounds tool-name probes (O2 mitigation)"
    # Distinctive tool_rules signals
    assert "fetch_project_readme" in prompt, "tool_rules must name the tool"
    # Cross-branch conciseness rule still applies
    assert "Length and disclosure" in prompt
    # Universal project_links rule applies
    assert "Project links" in prompt, "project_links is universal — must reach every branch including TECHNICAL"


def test_technical_branch_excludes_other_branch_sections(fixture_profile):
    """TECHNICAL must not pull narrative_summary / gap_inventory / logistics / personal_stories.

    Branch-shape leak guard: TECHNICAL is for project-deep Q + tool-name probes;
    other branches' sections would either over-share narrative or shift framing
    away from technical content.
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["TECHNICAL"], "generator")
    assert "NARRATIVE-MARKER" not in prompt
    assert "GAP-MARKER" not in prompt
    assert "LOGISTICS-MARKER" not in prompt
    assert "PERSONAL-STORIES-MARKER" not in prompt


def test_technical_branch_does_not_load_calibration_ladder_or_deflection(fixture_profile):
    """TECHNICAL relies on active_learning's own framing for calibration; deflection is BEHAVIOURAL-only.

    Per Q1 design: trust the model to infer depth from active_learning section content
    rather than wiring an explicit calibration_ladder rule. Deflection is BEHAVIOURAL-
    specific (P7 in LIMITATIONS.md governs whether to extract a cross-branch variant later).
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["TECHNICAL"], "generator")
    assert "Calibration ladder" not in prompt, "TECHNICAL does not load calibration_ladder; active_learning section's own framing handles tool-name probes"
    assert "Personal stories" not in prompt, "deflection is BEHAVIOURAL-only per P7"


def test_registry_has_all_five_branches_today():
    """REGISTRY exposes GENERIC + GAP + LOGISTICAL + BEHAVIOURAL + TECHNICAL — adding a sixth branch without test update is intentional friction.

    Phase 2 branch surface complete with #18; further branches would need a new acceptance
    criterion + spec discussion (no candidates today).
    """
    assert set(REGISTRY.keys()) == {"GENERIC", "GAP", "LOGISTICAL", "BEHAVIOURAL", "TECHNICAL"}

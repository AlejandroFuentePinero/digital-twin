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
    assert generic.branch_rules == ["concise_disclosure"]


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
    assert logistical.branch_rules == ["concise_disclosure"]


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
    assert behavioural.branch_rules == ["deflection", "concise_disclosure"]


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


def test_registry_has_generic_gap_logistical_and_behavioural_today():
    """REGISTRY exposes GENERIC + GAP + LOGISTICAL + BEHAVIOURAL — adding a fifth branch without test update is intentional friction."""
    assert set(REGISTRY.keys()) == {"GENERIC", "GAP", "LOGISTICAL", "BEHAVIOURAL"}

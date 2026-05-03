import pytest

from branches import REGISTRY, BranchSpec
from composer import PromptComposer
from profile import ProfileLoader
from rules import RULES, UNIVERSAL


@pytest.fixture
def fixture_profile(tmp_path):
    """Minimal profile fixture covering every section any registered branch loads."""
    p = tmp_path / "profile.md"
    p.write_text(
        "## identity\nIDENTITY-MARKER body.\n\n"
        "## narrative_summary\nNARRATIVE-MARKER body.\n\n"
        "## transfer_principles\nTRANSFER-MARKER body.\n\n"
        "## gap_inventory\nGAP-MARKER body — should not leak into GENERIC.\n\n"
        "## active_learning\nACTIVE-LEARNING-MARKER body.\n"
    )
    return ProfileLoader(p)


def test_gap_single_branch_loads_calibration_ladder_gap_inventory_and_active_learning(fixture_profile):
    """compose(['GAP']) includes the calibration_ladder rule, gap_inventory, and active_learning sections."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["GAP"], "generator")
    assert "Calibration ladder" in prompt, "GAP's branch_rule (calibration_ladder) must be loaded"
    assert "GAP-MARKER" in prompt, "GAP's gap_inventory section must be loaded"
    assert "ACTIVE-LEARNING-MARKER" in prompt, "GAP's active_learning section must be loaded so in-progress curriculum keywords are always available"
    # GENERIC-only sections must not leak in
    assert "NARRATIVE-MARKER" not in prompt
    assert "TRANSFER-MARKER" not in prompt


def test_multi_branch_unions_sections_and_rules_dedup_identity(fixture_profile):
    """compose(['GAP', 'GENERIC']) unions both branches' rules and sections; identity dedupes."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["GAP", "GENERIC"], "generator")
    # Both branches' rule and section content present
    assert "Calibration ladder" in prompt
    assert "IDENTITY-MARKER" in prompt
    assert "GAP-MARKER" in prompt
    assert "NARRATIVE-MARKER" in prompt
    assert "TRANSFER-MARKER" in prompt
    # identity appears in both branches' profile_sections — must dedupe (single occurrence)
    assert prompt.count("IDENTITY-MARKER") == 1, "identity section must dedupe across branches"


def test_generator_prompt_contains_universal_rules_and_generic_profile_sections(fixture_profile):
    """compose('GENERIC', 'generator') concatenates the four universal rules and the three GENERIC profile sections."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["GENERIC"], "generator")

    for key in UNIVERSAL:
        # Each universal rule's text appears in the prompt
        assert RULES[key].strip().splitlines()[0] in prompt, f"universal rule {key!r} missing"

    assert "IDENTITY-MARKER" in prompt
    assert "NARRATIVE-MARKER" in prompt
    assert "TRANSFER-MARKER" in prompt


def test_generator_and_guardrail_roles_produce_different_prompts(fixture_profile):
    """Same branch, different role — outputs differ and carry role-appropriate task framing."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    gen = composer.compose(["GENERIC"], "generator")
    judge = composer.compose(["GENERIC"], "guardrail")

    assert gen != judge, "generator and guardrail prompts must differ in role framing"
    # Generator framing tells the model to answer; guardrail tells it to evaluate.
    assert "answer" in gen.lower()
    assert "evaluate" in judge.lower()
    # Guardrail framing must NOT instruct the model to answer the user.
    assert "evaluate" not in gen.lower() or gen.lower().count("evaluate") < judge.lower().count("evaluate")


def test_retrieved_context_appears_verbatim_when_provided(fixture_profile):
    """Retrieved context is embedded verbatim in the prompt under a `## Retrieved context` header."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    ctx = "[publications.md — Iriarte 2021]\nViscacha population dynamics in the Andes."
    prompt = composer.compose(["GENERIC"], "generator", retrieved_context=ctx)
    assert ctx in prompt
    assert "## Retrieved context" in prompt


def test_no_retrieved_context_header_when_default_empty(fixture_profile):
    """No `## Retrieved context` header is emitted when retrieved_context is unset."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["GENERIC"], "generator")
    assert "## Retrieved context" not in prompt


def test_sections_outside_branch_spec_do_not_leak_into_prompt(fixture_profile):
    """GENERIC's `profile_sections` excludes `gap_inventory`, so its body must not appear in the prompt."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    prompt = composer.compose(["GENERIC"], "generator")
    assert "GAP-MARKER" not in prompt, "gap_inventory body leaked into GENERIC prompt"


def test_unknown_branch_raises_keyerror(fixture_profile):
    """compose() on a branch not in the registry raises KeyError — fail loudly on bad config."""
    composer = PromptComposer(fixture_profile, REGISTRY)
    with pytest.raises(KeyError):
        composer.compose(["DOES_NOT_EXIST"], "generator")


def test_concise_disclosure_rule_loads_into_generic_and_gap_branches(fixture_profile):
    """Both GENERIC and GAP carry the soft conciseness + progressive-disclosure rule.

    Discovered in #21 smoke-test: Q5.3 over-dumped (7-section + table response to
    "Tell me everything"); Q7.2 was correct content but excessive length. The rule
    nudges toward briefer answers without capping length — calibration ladder still
    governs depth of content.
    """
    composer = PromptComposer(fixture_profile, REGISTRY)
    assert "Length and disclosure" in composer.compose(["GENERIC"], "generator")
    assert "Length and disclosure" in composer.compose(["GAP"], "generator")

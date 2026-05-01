from branches import REGISTRY, BranchSpec


def test_generic_branch_matches_locked_spec():
    """REGISTRY['GENERIC'] carries the locked profile_sections / final_k / tools / branch_rules."""
    generic = REGISTRY["GENERIC"]
    assert isinstance(generic, BranchSpec)
    assert generic.name == "GENERIC"
    assert generic.profile_sections == ["identity", "narrative_summary", "transfer_principles"]
    assert generic.final_k == 6
    assert generic.tools == []
    assert generic.branch_rules == []


def test_registry_has_only_generic_today():
    """REGISTRY exposes GENERIC only — adding a branch without test update is intentional friction."""
    assert set(REGISTRY.keys()) == {"GENERIC"}

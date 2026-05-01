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


def test_gap_branch_matches_locked_spec():
    """REGISTRY['GAP'] carries the locked profile_sections / final_k / tools / branch_rules."""
    gap = REGISTRY["GAP"]
    assert isinstance(gap, BranchSpec)
    assert gap.name == "GAP"
    assert gap.profile_sections == ["identity", "gap_inventory"]
    assert gap.final_k == 6
    assert gap.tools == []
    assert gap.branch_rules == ["calibration_ladder"]


def test_registry_has_generic_and_gap_today():
    """REGISTRY exposes GENERIC + GAP only — adding a third branch without test update is intentional friction."""
    assert set(REGISTRY.keys()) == {"GENERIC", "GAP"}

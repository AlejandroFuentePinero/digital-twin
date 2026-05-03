from branches import REGISTRY, BranchSpec


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


def test_registry_has_generic_gap_and_logistical_today():
    """REGISTRY exposes GENERIC + GAP + LOGISTICAL — adding a fourth branch without test update is intentional friction."""
    assert set(REGISTRY.keys()) == {"GENERIC", "GAP", "LOGISTICAL"}

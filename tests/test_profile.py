import pytest

from profile import DEFAULT_PROFILE_PATH, ProfileLoader


def test_section_returns_body_for_a_single_named_block(tmp_path):
    """A profile with one `## identity` block exposes its body via .section('identity')."""
    p = tmp_path / "profile.md"
    p.write_text("## identity\nI am Alejandro.\n")
    loader = ProfileLoader(p)
    assert loader.section("identity") == "I am Alejandro."


def test_each_named_block_returns_only_its_own_body(tmp_path):
    """Multiple `## ` headings split into separate sections; bodies don't bleed across."""
    p = tmp_path / "profile.md"
    p.write_text(
        "## identity\nIdentity body.\n\n"
        "## narrative_summary\nNarrative body.\n\n"
        "## logistics\nLogistics body.\n"
    )
    loader = ProfileLoader(p)
    assert loader.section("identity") == "Identity body."
    assert loader.section("narrative_summary") == "Narrative body."
    assert loader.section("logistics") == "Logistics body."


def test_h3_subsections_stay_inside_parent_h2_body(tmp_path):
    """`### subheading` lines belong to the enclosing `## ` section, not their own."""
    p = tmp_path / "profile.md"
    p.write_text(
        "## gap_inventory\n"
        "Intro paragraph.\n\n"
        "### Cloud\nAWS Cloud Practitioner certified.\n\n"
        "### Frontend\nReact: exposure level only.\n"
    )
    loader = ProfileLoader(p)
    body = loader.section("gap_inventory")
    assert "Intro paragraph." in body
    assert "### Cloud" in body
    assert "AWS Cloud Practitioner certified." in body
    assert "### Frontend" in body
    assert "React: exposure level only." in body


def test_loader_discards_pre_section_preamble(tmp_path):
    """Content before the first `## ` heading never lands in any section body."""
    p = tmp_path / "profile.md"
    p.write_text(
        "# Profile — Alejandro\n\n"
        "This descriptive paragraph is meta-documentation and must not leak into prompts.\n\n"
        "## identity\nReal identity body.\n"
    )
    loader = ProfileLoader(p)
    assert loader.section("identity") == "Real identity body."
    # The preamble text must not appear in any section
    for name in ("identity",):
        assert "meta-documentation" not in loader.section(name)
        assert "Profile — Alejandro" not in loader.section(name)


def test_section_raises_keyerror_for_unknown_name(tmp_path):
    """`.section('does_not_exist')` raises KeyError — branches must declare valid section names."""
    p = tmp_path / "profile.md"
    p.write_text("## identity\nbody\n")
    loader = ProfileLoader(p)
    with pytest.raises(KeyError):
        loader.section("does_not_exist")


def test_empty_file_raises_valueerror(tmp_path):
    """Loading a profile.md with no `## ` headings raises ValueError — silent empty would mask bugs."""
    p = tmp_path / "profile.md"
    p.write_text("")
    with pytest.raises(ValueError):
        ProfileLoader(p)


def test_default_path_loads_the_real_profile_with_all_six_named_sections():
    """ProfileLoader() with no args parses data/profile.md and exposes all six named sections."""
    loader = ProfileLoader()
    expected = {
        "identity",
        "narrative_summary",
        "transfer_principles",
        "gap_inventory",
        "logistics",
        "personal_stories",
    }
    for name in expected:
        body = loader.section(name)
        assert body.strip(), f"section {name!r} is empty in {DEFAULT_PROFILE_PATH}"


def test_duplicate_headings_raise_valueerror(tmp_path):
    """Two `## identity` blocks raise ValueError — silent overwrite would lose half the section."""
    p = tmp_path / "profile.md"
    p.write_text(
        "## identity\nFirst body.\n\n"
        "## identity\nSecond body.\n"
    )
    with pytest.raises(ValueError):
        ProfileLoader(p)

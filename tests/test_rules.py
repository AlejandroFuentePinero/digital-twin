from rules import RULES, UNIVERSAL


def test_universal_keys_resolve_to_non_empty_rule_text():
    """Every UNIVERSAL key resolves to non-empty rule text in RULES."""
    for key in UNIVERSAL:
        assert key in RULES
        assert isinstance(RULES[key], str)
        assert RULES[key].strip(), f"RULES[{key!r}] is empty"


def test_universal_lists_the_four_locked_keys_in_order():
    """UNIVERSAL is exactly the four locked keys: persona, scope, security, numerical_completeness."""
    assert UNIVERSAL == ["persona", "scope", "security", "numerical_completeness"]

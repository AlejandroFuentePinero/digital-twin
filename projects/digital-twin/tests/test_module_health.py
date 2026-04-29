"""Tests for the pure helpers in src/module_health.py.

The Gradio rendering, subprocess invocation, and build_app() wiring are
intentionally untested (see PRD #7) — they are tooling glue best verified by
launching the dashboard. Only the pure helpers (humanize, parse_report) are
covered here, and only without mocks.
"""

from module_health import humanize, parse_report


def _test_entry(nodeid: str, outcome: str = "passed") -> dict:
    """Minimal pytest-json-report test entry."""
    return {
        "nodeid": nodeid,
        "outcome": outcome,
        "lineno": 1,
        "setup": {"outcome": "passed"},
        "call": {"outcome": outcome},
        "teardown": {"outcome": "passed"},
    }


# ---------------------------------------------------------------------------
# humanize
# ---------------------------------------------------------------------------


def test_humanize_strips_test_prefix_and_sentence_cases():
    """Humanize turns a test function name into a sentence-cased label."""
    assert humanize("test_log_creates_parent_directory") == "Log creates parent directory"


# ---------------------------------------------------------------------------
# parse_report
# ---------------------------------------------------------------------------


def test_parse_report_groups_tests_by_source_file():
    """Each test_*.py file becomes its own Module."""
    report = {
        "tests": [
            _test_entry("projects/digital-twin/tests/test_logger.py::test_a"),
            _test_entry("projects/digital-twin/tests/test_logger.py::test_b"),
            _test_entry("projects/digital-twin/tests/test_guardrail.py::test_c"),
        ]
    }

    modules = parse_report(report)

    assert len(modules) == 2


def test_parse_report_derives_module_name_from_filename():
    """test_guardrail.py becomes the module name 'guardrail'."""
    report = {"tests": [_test_entry("projects/digital-twin/tests/test_guardrail.py::test_x")]}

    modules = parse_report(report)

    assert modules[0].name == "guardrail"


def test_parse_report_maps_pytest_outcomes_to_status_labels():
    """passed → PASS, failed → FAIL, error → ERROR, skipped → SKIP."""
    report = {
        "tests": [
            _test_entry("tests/test_x.py::a", outcome="passed"),
            _test_entry("tests/test_x.py::b", outcome="failed"),
            _test_entry("tests/test_x.py::c", outcome="error"),
            _test_entry("tests/test_x.py::d", outcome="skipped"),
        ]
    }

    [module] = parse_report(report)
    statuses = [t.status for t in module.tests]

    assert statuses == ["PASS", "FAIL", "ERROR", "SKIP"]


def test_parse_report_counts_passed_and_total_per_module():
    """Module exposes passed/total for the 'X/Y' header — only PASS counts as passed."""
    report = {
        "tests": [
            _test_entry("tests/test_x.py::a", outcome="passed"),
            _test_entry("tests/test_x.py::b", outcome="failed"),
            _test_entry("tests/test_x.py::c", outcome="passed"),
            _test_entry("tests/test_x.py::d", outcome="skipped"),
        ]
    }

    [module] = parse_report(report)

    assert module.passed == 2
    assert module.total == 4


def test_parse_report_humanizes_test_labels():
    """Each Test carries a humanized label derived from the function name."""
    report = {"tests": [_test_entry("tests/test_x.py::test_log_creates_parent_directory")]}

    [module] = parse_report(report)

    assert module.tests[0].label == "Log creates parent directory"


def test_parse_report_returns_empty_list_when_no_tests_collected():
    """An empty pytest run does not crash the dashboard."""
    assert parse_report({"tests": []}) == []
    assert parse_report({}) == []

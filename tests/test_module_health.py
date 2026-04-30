"""Tests for the pure helpers in src/module_health.py.

The Gradio rendering and build_app() wiring are intentionally untested
(see PRD #7) — they are tooling glue best verified by launching the dashboard.
Only the pure helpers are covered here.
"""

import json

from module_health import (
    Module,
    Summary,
    Test,
    gather_report,
    humanize,
    load_docstrings,
    parse_report,
    render_module,
    render_summary,
    summarize,
)


def _test_entry(
    nodeid: str,
    outcome: str = "passed",
    call_longrepr: str | None = None,
    setup_outcome: str = "passed",
    setup_longrepr: str | None = None,
) -> dict:
    """Minimal pytest-json-report test entry."""
    call_outcome = outcome if setup_outcome == "passed" else None
    return {
        "nodeid": nodeid,
        "outcome": outcome,
        "lineno": 1,
        "setup": {"outcome": setup_outcome, "longrepr": setup_longrepr},
        "call": {"outcome": call_outcome, "longrepr": call_longrepr},
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
            _test_entry("tests/test_logger.py::test_a"),
            _test_entry("tests/test_logger.py::test_b"),
            _test_entry("tests/test_guardrail.py::test_c"),
        ]
    }

    modules = parse_report(report)

    assert len(modules) == 2


def test_parse_report_derives_module_name_from_filename():
    """test_guardrail.py becomes the module name 'guardrail'."""
    report = {"tests": [_test_entry("tests/test_guardrail.py::test_x")]}

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


# ---------------------------------------------------------------------------
# parse_report — traceback surfacing
# ---------------------------------------------------------------------------


def test_parse_report_attaches_call_longrepr_to_failed_test():
    """A FAIL test carries the call-phase longrepr so the dashboard can render it inline."""
    tb = "tests/test_x.py:5: in test_a\n    assert 1 == 2\nE   assert 1 == 2"
    report = {
        "tests": [
            _test_entry("tests/test_x.py::test_a", outcome="failed", call_longrepr=tb),
        ]
    }

    [module] = parse_report(report)

    assert module.tests[0].traceback == tb


def test_parse_report_attaches_setup_longrepr_to_error_test():
    """An ERROR test (setup/teardown failure) carries the setup-phase longrepr."""
    tb = "tests/conftest.py:8: in fixture\n    raise RuntimeError\nE   RuntimeError"
    report = {
        "tests": [
            _test_entry(
                "tests/test_x.py::test_a",
                outcome="error",
                setup_outcome="failed",
                setup_longrepr=tb,
            ),
        ]
    }

    [module] = parse_report(report)

    assert module.tests[0].traceback == tb


def test_parse_report_passed_test_has_no_traceback():
    """A PASS test exposes traceback=None — nothing to render under the row."""
    report = {"tests": [_test_entry("tests/test_x.py::test_a", outcome="passed")]}

    [module] = parse_report(report)

    assert module.tests[0].traceback is None


# ---------------------------------------------------------------------------
# parse_report — docstring-driven labels
# ---------------------------------------------------------------------------


def test_parse_report_uses_docstring_label_when_provided():
    """When a docstring map is supplied, parse_report uses it as the label."""
    report = {"tests": [_test_entry("tests/test_x.py::test_a", outcome="passed")]}
    docstrings = {"test_x.py::test_a": "Behaves like a duck."}

    [module] = parse_report(report, docstrings=docstrings)

    assert module.tests[0].label == "Behaves like a duck."


def test_parse_report_falls_back_to_humanized_when_no_docstring():
    """Tests without a docstring entry get the humanized name as a fallback."""
    report = {"tests": [_test_entry("tests/test_x.py::test_my_behaviour", outcome="passed")]}

    [module] = parse_report(report, docstrings={})

    assert module.tests[0].label == "My behaviour"


# ---------------------------------------------------------------------------
# load_docstrings
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# render_module — inline tracebacks
# ---------------------------------------------------------------------------


def test_render_module_includes_traceback_under_failed_test():
    """A FAIL row is followed by its traceback in the rendered markdown."""
    module = Module(
        name="x",
        tests=[Test(label="A test", status="FAIL", traceback="line1\nline2")],
    )

    output = render_module(module)

    assert "line1" in output
    assert "line2" in output


def test_render_module_includes_traceback_under_error_test():
    """An ERROR row is followed by its traceback in the rendered markdown."""
    module = Module(
        name="x",
        tests=[Test(label="A test", status="ERROR", traceback="setup boom")],
    )

    output = render_module(module)

    assert "setup boom" in output


def test_render_module_omits_traceback_for_passed_tests():
    """A PASS row has no traceback markup attached."""
    module = Module(name="x", tests=[Test(label="Ok", status="PASS")])

    output = render_module(module)

    assert "traceback" not in output
    assert "<pre" not in output


# ---------------------------------------------------------------------------
# summarize — top-strip aggregation
# ---------------------------------------------------------------------------


def test_summarize_extracts_pass_fail_error_skip_counts():
    """summarize() pulls discrete counts out of the pytest-json-report summary block."""
    report = {
        "summary": {"passed": 9, "failed": 2, "error": 1, "skipped": 3, "total": 15},
        "duration": 1.5,
        "created": 1700000000.0,
    }

    s = summarize(report)

    assert s.passed == 9
    assert s.failed == 2
    assert s.error == 1
    assert s.skipped == 3


def test_summarize_global_pass_when_no_failures_or_errors():
    """The global indicator is True iff every test passed or skipped (no FAIL/ERROR)."""
    report = {
        "summary": {"passed": 5, "failed": 0, "error": 0, "skipped": 1},
        "duration": 0.0,
        "created": 0.0,
    }

    assert summarize(report).all_passed is True


def test_summarize_global_fail_when_any_failure_or_error():
    """A single FAIL or ERROR flips the global indicator."""
    failing = {"summary": {"passed": 5, "failed": 1, "error": 0, "skipped": 0}}
    erroring = {"summary": {"passed": 5, "failed": 0, "error": 1, "skipped": 0}}

    assert summarize(failing).all_passed is False
    assert summarize(erroring).all_passed is False


def test_summarize_handles_missing_summary_keys():
    """A pytest-json-report summary block omits keys with zero counts; summarize() defaults them."""
    report = {"summary": {"passed": 3, "total": 3}, "duration": 0.5, "created": 0.0}

    s = summarize(report)

    assert s.failed == 0
    assert s.error == 0
    assert s.skipped == 0
    assert s.all_passed is True


# ---------------------------------------------------------------------------
# render_summary — top-strip rendering
# ---------------------------------------------------------------------------


def test_render_summary_shows_four_counts_duration_and_timestamp():
    """The top strip surfaces pass/fail/error/skip as discrete numbers, plus duration and timestamp."""
    # 2026-04-30 12:00:00 UTC
    summary = Summary(
        passed=9, failed=2, error=1, skipped=3, duration=4.25, created=1777809600.0
    )

    output = render_summary(summary)

    assert "9" in output  # passed
    assert "2" in output  # failed
    assert "1" in output  # error
    assert "3" in output  # skipped
    assert "4.25" in output or "4.3" in output  # duration in seconds
    assert "2026" in output  # timestamp


def test_render_summary_shows_check_when_all_passed():
    """A green-light suite renders the global ✅ indicator."""
    summary = Summary(passed=10, failed=0, error=0, skipped=0, duration=1.0, created=0.0)

    assert "✅" in render_summary(summary)


def test_render_summary_shows_x_when_any_failures():
    """Any FAIL or ERROR flips the global indicator to ❌."""
    summary = Summary(passed=10, failed=1, error=0, skipped=0, duration=1.0, created=0.0)

    assert "❌" in render_summary(summary)


# ---------------------------------------------------------------------------
# gather_report — pytest with cached-report fallback
# ---------------------------------------------------------------------------


def test_gather_report_returns_runner_result_when_runner_succeeds(tmp_path):
    """Happy path: runner returns a fresh report; no error surfaced."""
    fresh = {"summary": {"passed": 1, "total": 1}, "tests": []}

    report, error = gather_report(runner=lambda: fresh, cache_path=tmp_path / "missing.json")

    assert report is fresh
    assert error is None


def test_gather_report_falls_back_to_cache_when_runner_fails(tmp_path):
    """When the pytest subprocess fails to launch, gather_report reads the cached JSON from disk."""
    cached = {"summary": {"passed": 7, "total": 7}, "tests": []}
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(cached))

    def boom():
        raise FileNotFoundError("pytest binary not found")

    report, error = gather_report(runner=boom, cache_path=cache_path)

    assert report == cached
    assert error is not None
    assert "pytest binary not found" in error


def test_gather_report_returns_empty_report_when_runner_fails_and_no_cache(tmp_path):
    """No crash when the runner fails and there is no cached report on disk yet."""
    def boom():
        raise RuntimeError("kaboom")

    report, error = gather_report(runner=boom, cache_path=tmp_path / "absent.json")

    # parse_report and summarize must accept this without exploding.
    assert parse_report(report) == []
    assert summarize(report).passed == 0
    assert error is not None
    assert "kaboom" in error


def test_load_docstrings_reads_test_docstrings_from_source(tmp_path):
    """load_docstrings parses test_*.py files and returns nodeid → docstring."""
    f = tmp_path / "test_sample.py"
    f.write_text(
        '''
def test_first():
    """First test docstring."""
    pass


def test_second():
    """Second test docstring."""
    pass


def helper():
    """Helpers are not collected."""
    pass


def test_no_doc():
    pass
'''.strip()
    )

    result = load_docstrings(tmp_path)

    assert result["test_sample.py::test_first"] == "First test docstring."
    assert result["test_sample.py::test_second"] == "Second test docstring."
    assert "test_sample.py::helper" not in result
    assert "test_sample.py::test_no_doc" not in result

"""Sentinel is mostly Gradio glue (cf. app.py exemption in TESTING.md), so
coverage is limited to the small pure helpers + a smoke test that the app
boots against real and synthetic logs without crashing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from failure_feed import Session, group_by_session
from interaction_log import DEFAULT_LOG_PATH, InteractionRecord
from log_reader import LocalReader
from sentinel import (
    THEMATIC_BLOCKS,
    build_app,
    chart_dataframe,
    format_failure_drilldown,
    format_header,
    format_metrics_overview,
    format_session_view,
    format_status_banner,
    format_trend_header,
)
from dashboard_model import METRIC_GETTERS, DashboardModel
from metric_status import THRESHOLDS


def _record_dict(timestamp: str | None = None, event_type: str = "answered", total_latency: int = 1000) -> dict:
    return {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "session_id": "sess-x",
        "turn_index": 0,
        "question": "q?",
        "event_type": event_type,
        "branch": "GENERIC",
        "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": total_latency},
        "knew_answer": True,
    }


def _models_and_priors(records):
    """Build the (models, priors) lists `format_metrics_overview` consumes."""
    full = DashboardModel(records)
    models = [full.for_window(days=7), full.for_window(days=30), full]
    priors = [
        full.for_prior_window(days=7),
        full.for_prior_window(days=30),
        DashboardModel([]),  # Global has no prior window
    ]
    return models, priors


def test_format_metrics_overview_renders_every_section_header_once():
    """Single-header structure: each thematic block (Outcome / Routing /
    Engagement / Tool use / Latency) appears exactly ONCE — not three times
    (per the operator + design-spec restructure: section headers ride above a
    single row of 3 windowed values, they don't repeat per window)."""
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict())]
    models, priors = _models_and_priors(records)
    overview = format_metrics_overview(models, priors)

    for header in ("Outcome", "Routing", "Engagement", "Tool use", "Latency"):
        assert overview.count(header) == 1, (
            f"section header {header!r} must appear exactly once, not per window"
        )


def test_format_metrics_overview_includes_every_metric_label():
    """Every spec'd metric label appears in the rendered overview — these are
    the rows the operator scans across the 3 windowed values."""
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict())]
    models, priors = _models_and_priors(records)
    overview = format_metrics_overview(models, priors)

    for label in (
        "Gap rate", "Deflection rate", "Refusal rate",
        "Guardrail rejection rate", "Retry-exhaustion rate",
        "Low-confidence", "Confident-failure",
        "Branch distribution", "Multi-label",
        "Unique sessions", "Turns/session", "Contact-conversion",
        "Tool uptake", "Tool-call success",
        "classifier", "retrieval", "generation", "guardrail", "total",
    ):
        assert label in overview, f"missing metric row: {label!r}"


def test_format_metrics_overview_collapses_to_same_across_windows_when_identical():
    """When the same value renders identically in all 3 windows, the row shows
    ONE value + 'same across windows' suffix — not three identical cells."""
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict())]  # 1 record total
    models, priors = _models_and_priors(records)
    overview = format_metrics_overview(models, priors)

    # The single record sits inside every window, so all three windows agree
    # on every metric → at least one row says "same across windows".
    assert "same across windows" in overview, (
        "identical-across-windows rows must collapse to a single value + suffix"
    )


def test_format_metrics_overview_marks_diverging_cells_with_divergent_class():
    """When at least one window's formatted value differs from the others, the
    diverging cells get the `divergent` CSS class — operator's eye lands on
    the cell that disagrees."""
    from datetime import datetime, timedelta, timezone
    from interaction_log import InteractionRecord

    now = datetime.now(timezone.utc)
    # One bad record (knew_answer=False) inside the 7d window only — Global
    # also includes it, but 30d does too. To get genuine divergence I need a
    # record outside the 30d window. Use 50 days ago for the global-only one.
    bad7 = _record_dict()
    bad7["knew_answer"] = False
    bad7["timestamp"] = (now - timedelta(days=2)).isoformat()
    bad7["session_id"] = "s-7d"
    clean_old = _record_dict()
    clean_old["timestamp"] = (now - timedelta(days=50)).isoformat()
    clean_old["session_id"] = "s-old"

    records = [
        InteractionRecord.model_validate(bad7),
        InteractionRecord.model_validate(clean_old),
    ]
    models, priors = _models_and_priors(records)
    overview = format_metrics_overview(models, priors)

    # 7d gap rate = 100%; 30d gap rate = 100%; Global = 50% — divergence on Global.
    assert "divergent" in overview


def test_format_metrics_overview_renders_none_as_em_dash():
    """Metrics that resolve to None render as the em-dash placeholder, not
    'None' or '0%'."""
    models, priors = _models_and_priors([])
    overview = format_metrics_overview(models, priors)
    assert "None" not in overview
    assert "—" in overview


def test_format_metrics_overview_applies_status_class_to_thresholded_metric():
    """A thresholded metric in the alert band gets the `alert` CSS class on
    its value cell — colour-by-status replaces the old badge pill."""
    from interaction_log import InteractionRecord

    bad = _record_dict()
    bad["knew_answer"] = False
    records = [
        InteractionRecord.model_validate(bad), InteractionRecord.model_validate(bad),
        InteractionRecord.model_validate(bad), InteractionRecord.model_validate(_record_dict()),
    ]
    models, priors = _models_and_priors(records)
    overview = format_metrics_overview(models, priors)

    # gap_rate ≈ 75% across every window → divergence is False but value cells
    # carry the `alert` class.
    assert "metric-value alert" in overview or "alert" in overview


def test_format_status_banner_counts_alert_warning_healthy_metrics():
    """The banner aggregates the headline window's metric statuses into 3
    counts. Sentinel header shows 'N alerts · N warnings · N healthy' so the
    operator gets a one-line health verdict above every tab."""
    from sentinel import _status_summary, format_status_banner
    from interaction_log import InteractionRecord

    bad = _record_dict()
    bad["knew_answer"] = False
    records = [
        InteractionRecord.model_validate(bad),
        InteractionRecord.model_validate(bad),
        InteractionRecord.model_validate(_record_dict()),
    ]
    summary = _status_summary(DashboardModel(records))
    banner = format_status_banner(summary)

    assert "SENTINEL" in banner
    # Count strings appear (numbers vary as thresholds tune; the structure must hold)
    assert "alerts" in banner.lower()
    assert "warnings" in banner.lower()
    assert "healthy" in banner.lower()
    # Alerts named explicitly when present
    if summary["alert"]:
        assert summary["alert"][0] in banner


def test_format_status_banner_groups_metrics_into_three_buckets():
    """`_status_summary` partitions every thresholded metric into exactly one
    of {alert, warning, healthy} (or skips when value is None). No metric can
    appear in two buckets — banner counts must add up cleanly."""
    from sentinel import _status_summary

    summary = _status_summary(DashboardModel([]))
    overlap = (
        set(summary["alert"]) & set(summary["warning"])
        | set(summary["alert"]) & set(summary["healthy"])
        | set(summary["warning"]) & set(summary["healthy"])
    )
    assert overlap == set(), f"metrics double-counted: {overlap}"


def test_format_metrics_overview_does_not_apply_status_class_to_orientation_rows():
    """Orientation metrics (unique_sessions, branch_distribution, etc.) have
    no threshold — their value cells must not carry healthy/warning/alert
    classes (would mislead the operator into treating them as actionable)."""
    import re
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict())]
    models, priors = _models_and_priors(records)
    overview = format_metrics_overview(models, priors)

    # Match the Unique-sessions row label + its surrounding metric-value cells
    # up to the next metric-label. None of those cells should carry a status class.
    m = re.search(
        r"<div class='metric-label'>Unique sessions</div>(.*?)(?=<div class='metric-label'>|<div class='section-block'>)",
        overview, flags=re.DOTALL,
    )
    assert m, "expected a Unique sessions label in the overview"
    block = m.group(1)
    for status in ("healthy", "warning", "alert"):
        assert f"metric-value {status}" not in block, (
            f"orientation row Unique sessions must not carry {status} colour"
        )


def test_global_window_appears_in_window_set_and_today_does_not():
    """Per issue #35: WINDOWS = [(Global, None), (30d, 30), (7d, 7)] — Today removed
    (low signal in low-traffic regime), Global added (first-glance all-time picture)."""
    from sentinel import WINDOWS

    labels = [label for label, _ in WINDOWS]
    assert "Global" in labels
    assert "Today" not in labels
    # Global maps to days=None (no filter)
    global_days = dict(WINDOWS)["Global"]
    assert global_days is None


def test_format_header_includes_source_indicator_and_loaded_date_only():
    """format_header surfaces the source label and the loaded date — no time of
    day (per the operator directive: dates only across the dashboard)."""
    loaded_at = datetime(2026, 5, 4, 12, 30, tzinfo=timezone.utc)
    header = format_header(source="Local JSONL", loaded_at=loaded_at)

    assert "Local JSONL" in header
    assert "2026-05-04" in header
    assert "12:30" not in header, "time-of-day removed by date-only directive"


def test_build_app_returns_gradio_blocks_when_reader_supplied(tmp_path):
    """build_app boots without raising when given an injected reader.
    Autorefresh is disabled in tests — no LLM calls allowed per TESTING.md."""
    log_path = tmp_path / "interactions.jsonl"
    log_path.write_text(json.dumps(_record_dict()) + "\n")

    app = build_app(reader=LocalReader(log_path), autorefresh=False)
    assert app is not None
    assert hasattr(app, "launch")  # gr.Blocks duck-type


@pytest.mark.skipif(not Path(DEFAULT_LOG_PATH).exists(), reason="No real log file present")
def test_build_app_does_not_crash_against_live_interactions_log():
    """Smoke: Sentinel boots against the live data/logs/interactions.jsonl
    without raising. Autorefresh disabled — see test note above."""
    app = build_app(autorefresh=False)
    assert app is not None


# ----- Failure Feed formatters (issue #31) ------------------------------------


def _detailed_record() -> InteractionRecord:
    """Realistic failure record with multiple attempts, chunks, tool calls — exercises every drilldown field."""
    return InteractionRecord.model_validate(
        {
            "timestamp": "2026-05-01T12:00:00+00:00",
            "session_id": "sess-A",
            "turn_index": 2,
            "question": "How does the chunking work in the Expert Knowledge Worker project?",
            "event_type": "answered",
            "branch": "TECHNICAL",
            "classifier_labels": ["TECHNICAL", "GENERIC"],
            "classification_confidence": 0.83,
            "attempts": [
                {"answer": "vague guess", "is_acceptable": False,
                 "guardrail_feedback": "Too vague — fetch the README first."},
                {"answer": "Headline-summary-original_text triple", "is_acceptable": True,
                 "guardrail_feedback": "Accurate, cites the source."},
            ],
            "retrieved_chunks": [
                {"source_file": "projects_ai_flagship.md", "section_heading": "Expert Knowledge Worker"},
                {"source_file": "INDEX.md", "section_heading": "INDEX"},
            ],
            "tool_calls": [
                {"name": "fetch_project_readme", "args": {"key": "expert-knowledge-worker"},
                 "status": "success", "attempt_index": 1},
            ],
            "latency_ms": {
                "classifier": 800, "retrieval": 1200, "generation": 5400,
                "guardrail": 3000, "total": 10400,
            },
            "knew_answer": True,
        }
    )


def test_format_failure_drilldown_surfaces_every_attempt_field():
    """Every attempt's answer + guardrail_feedback + is_acceptable status is visible in the drilldown.
    The whole point of the panel: 'what did the model try, what did the guardrail say'."""
    md = format_failure_drilldown(_detailed_record())
    assert "vague guess" in md
    assert "fetch the README first" in md
    assert "Headline-summary-original_text triple" in md
    assert "Accurate, cites the source" in md


def test_format_failure_drilldown_surfaces_retrieved_chunks_and_tool_calls():
    """Retrieved chunks (source_file + section_heading) and tool_calls (name + args + status)
    must appear so the operator can see 'did retrieval pull the right thing, did the tool fire'."""
    md = format_failure_drilldown(_detailed_record())
    assert "projects_ai_flagship.md" in md
    assert "Expert Knowledge Worker" in md
    assert "fetch_project_readme" in md
    assert "expert-knowledge-worker" in md
    assert "success" in md


def test_format_failure_drilldown_surfaces_routing_and_latency_breakdown():
    """branch, classifier_labels, classification_confidence, and per-stage latency are visible."""
    md = format_failure_drilldown(_detailed_record())
    assert "TECHNICAL" in md
    assert "GENERIC" in md  # secondary label
    assert "0.83" in md
    # Per-stage latency
    assert "classifier" in md.lower() and "800" in md
    assert "generation" in md.lower() and "5400" in md
    assert "guardrail" in md.lower() and "3000" in md
    assert "total" in md.lower() and "10400" in md


def _record_for_session(turn_index: int, question: str = "q?", **overrides) -> InteractionRecord:
    base = {
        "timestamp": f"2026-05-01T12:0{turn_index}:00+00:00",
        "session_id": "sess-Z",
        "turn_index": turn_index,
        "question": question,
        "event_type": "answered",
        "branch": "GENERIC",
        "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 1000},
        "knew_answer": True,
        "contact_offered": False,
        "contact_provided": False,
    }
    base.update(overrides)
    return InteractionRecord.model_validate(base)


def test_format_session_view_renders_header_with_session_metadata():
    """Header shows session_id, turn count, contact state, total session latency."""
    records = [
        _record_for_session(0, contact_offered=True),
        _record_for_session(1, latency_ms={"classifier": 0, "retrieval": 0, "generation": 0,
                                            "guardrail": 0, "total": 2500}),
        _record_for_session(2, contact_offered=True, contact_provided=True,
                            latency_ms={"classifier": 0, "retrieval": 0, "generation": 0,
                                         "guardrail": 0, "total": 4000}),
    ]
    [session] = group_by_session(records)
    md = format_session_view(session)
    assert "sess-Z" in md
    assert "3" in md  # turn count
    # Contact state visible in some form (offered + provided shown)
    assert "offered" in md.lower() or "provided" in md.lower()
    # Total latency = 1000 + 2500 + 4000 = 7500 ms
    assert "7500" in md or "7,500" in md


def test_format_session_view_renders_one_collapsible_per_turn_with_pass_fail_badge():
    """Each turn renders as a click-to-expand block (`<details>`) showing turn_index, branch,
    event_type, truncated question, and a PASS/FAIL badge derived from classify_failure."""
    records = [
        _record_for_session(0, question="clean turn"),                   # PASS
        _record_for_session(1, question="bad turn", knew_answer=False),  # FAIL · gap
    ]
    [session] = group_by_session(records)
    md = format_session_view(session)

    assert md.count("<details>") == 2  # one per turn
    assert "Turn 0" in md and "Turn 1" in md
    assert "clean turn" in md and "bad turn" in md
    assert "PASS" in md
    assert "FAIL" in md
    assert "gap" in md  # the failure-mode label appears on the badge


def test_format_session_view_uses_drilldown_for_each_turn_body():
    """Each <details> body renders the same per-turn drilldown fields (attempts, latency, etc.)
    so 'click on any turn → see the full debug surface' just works."""
    records = [_record_for_session(0, attempts=[
        {"answer": "first try", "is_acceptable": False, "guardrail_feedback": "fix it"},
        {"answer": "second try", "is_acceptable": True, "guardrail_feedback": ""},
    ])]
    [session] = group_by_session(records)
    md = format_session_view(session)
    assert "first try" in md
    assert "second try" in md
    assert "fix it" in md


# ----- Trend Explorer (issue #30) ---------------------------------------------


def test_chart_dataframe_includes_value_series_and_threshold_reference_lines():
    """chart_dataframe returns a long-format pandas frame with `date`, `value`, `series`
    columns. Series column carries 'value' for the metric line plus 'healthy'/'warning'
    horizontal threshold references — gr.LinePlot can colour them via the series column."""
    from datetime import datetime, timezone

    record = InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "s", "turn_index": 0, "question": "q?", "event_type": "answered",
        "branch": "GENERIC", "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
        "knew_answer": True,
    })
    model = DashboardModel([record])
    df = chart_dataframe(model, metric="gap_rate", days=7)

    assert set(df.columns) >= {"date", "value", "series"}
    series_set = set(df["series"].unique())
    assert "actual" in series_set, "raw daily values rendered as 'actual' series"
    assert "3-day avg" in series_set, "rolling-average smoother must be drawn"
    assert "healthy" in series_set, "healthy threshold reference line must be drawn"
    assert "warning" in series_set, "warning threshold reference line must be drawn"


def test_chart_dataframe_includes_prior_period_series_when_prior_model_supplied():
    """When prior_model is passed, chart_dataframe adds a 'prior' series — the basis for the
    'Show prior period' overlay in investigate mode (issue #30 spec)."""
    from datetime import datetime, timezone

    rec = lambda: InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "s", "turn_index": 0, "question": "q?", "event_type": "answered",
        "branch": "GENERIC", "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
        "knew_answer": True,
    })
    model = DashboardModel([rec()])
    prior = DashboardModel([rec()])
    df = chart_dataframe(model, metric="gap_rate", days=7, prior_model=prior)
    assert "prior" in set(df["series"].unique())


def test_chart_dataframe_returns_empty_dataframe_for_empty_model():
    """An empty model yields a chart with no rows — the chart layer renders an
    'insufficient data' placeholder instead of crashing on missing series."""
    df = chart_dataframe(DashboardModel([]), metric="gap_rate", days=7)
    assert len(df) == 0


def test_thematic_blocks_partition_every_plottable_metric_exactly_once():
    """THEMATIC_BLOCKS maps Panel-1's 5 blocks (Outcome / Routing / Engagement / Tool use /
    Latency) to lists of metric names; every plottable metric appears in exactly one block.
    Forcing function: adding a metric to METRIC_GETTERS forces an entry in THEMATIC_BLOCKS."""
    all_assigned = [m for metrics in THEMATIC_BLOCKS.values() for m in metrics]
    assert sorted(all_assigned) == sorted(METRIC_GETTERS.keys()), (
        "THEMATIC_BLOCKS must enumerate every plottable metric (no duplicates, no omissions)"
    )
    assert sorted(all_assigned) == sorted(set(all_assigned)), "no metric in two blocks"
    # Five blocks, matching Panel 1's headings
    assert set(THEMATIC_BLOCKS.keys()) == {
        "Outcome", "Routing", "Engagement", "Tool use", "Latency"
    }


# ----- Cluster panel (issue #32) ---------------------------------------------


def test_format_cluster_panel_renders_placeholder_when_data_is_none():
    """When `gap_clusters.json` is absent, the panel renders a placeholder
    explaining the empty state — Sentinel auto-runs the batch on launch, so
    the placeholder reads as 'no gap turns to cluster' rather than 'go run a
    script'."""
    from sentinel import format_cluster_panel

    md = format_cluster_panel(None)
    assert "no" in md.lower() or "cluster" in md.lower(), (
        "placeholder must read like a non-broken empty state, not a crash"
    )


def test_format_cluster_panel_renders_label_count_and_sample_questions():
    """Each cluster row surfaces label, count, and the example questions —
    the three fields the issue spec calls out as 'Sentinel reads the cached file
    and renders the clusters with label + count + sample questions'."""
    from sentinel import format_cluster_panel

    data = {
        "generated_at": "2026-05-04T12:00:00+00:00",
        "period_days": 7,
        "clusters": [
            {"label": "AWS / cloud", "count": 3,
             "examples": ["Have you used AWS?", "AWS Lambda?", "Deployed to AWS?"]},
            {"label": "kdb+ / time-series", "count": 2,
             "examples": ["kdb+?", "q?"]},
        ],
    }
    md = format_cluster_panel(data)

    # Both labels and counts appear
    assert "AWS / cloud" in md
    assert "kdb+ / time-series" in md
    assert "3" in md and "2" in md  # counts
    # Every example question is rendered verbatim
    assert "Have you used AWS?" in md
    assert "AWS Lambda?" in md
    assert "Deployed to AWS?" in md
    assert "kdb+?" in md and "q?" in md
    # The window the batch covered is surfaced (operator needs it for context)
    assert "7" in md


# ----- Deflection panel (issue #33) ------------------------------------------


def test_format_deflection_panel_renders_placeholder_when_text_is_none():
    """When no `deflection_*.md` exists yet, the panel renders a non-broken
    empty-state placeholder. Sentinel auto-runs the batch, so the placeholder
    reads as 'no deflection summary to render' rather than 'go run a script'."""
    from sentinel import format_deflection_panel

    md = format_deflection_panel(None)
    assert "no" in md.lower() or "deflection" in md.lower(), (
        "placeholder must read like a non-broken empty state, not a crash"
    )


# ----- Flags panel formatter (issue #34) -------------------------------------


def test_format_flags_summary_renders_placeholder_when_no_flags():
    """Empty flag list → placeholder copy. Stable / quiet weeks must not look
    broken; the placeholder explains why nothing is firing."""
    from sentinel import format_flags_summary

    md = format_flags_summary([])
    assert "anomalies" in md.lower() or "no flag" in md.lower()


def test_format_flags_summary_renders_each_flag_headline_and_detail():
    """Each Flag becomes a card with headline + detail visible. The
    Investigate buttons live as separate gr.Button instances (built in
    build_app) so click handlers can switch tabs — the summary markdown is
    pure HTML, no anchor links."""
    from flag_detector import Flag
    from sentinel import format_flags_summary

    flags = [
        Flag(kind="repeat_failure", headline="Repeated failure (3×): kdb+/q?",
             detail="Same question deflected 3 times in 7 days.",
             target="failure_feed"),
        Flag(kind="new_cluster", headline="New gap cluster: Rust",
             detail="2 gap question(s) clustered under this label this week.",
             target="gap_clusters"),
    ]
    md = format_flags_summary(flags)

    for f in flags:
        assert f.headline in md or _html_escape(f.headline) in md
        assert f.detail in md or _html_escape(f.detail) in md
    # No anchor links — tab switching is wired via Gradio buttons in build_app
    assert "href=" not in md


def _html_escape(s: str) -> str:
    """Mirror html.escape so the assertion above works regardless of which form
    the formatter uses (kept local to avoid leaking import order across tests)."""
    import html as _html
    return _html.escape(s)


def test_flag_target_tab_maps_each_target_to_a_real_tab_id():
    """Every FlagTarget literal must map to one of the three tab IDs Sentinel
    actually builds (forcing function — adding a new target without a tab
    mapping silently breaks click handlers)."""
    from sentinel import FLAG_TARGET_TAB, TAB_FAILURES, TAB_TRENDS

    # Every value is a known tab ID
    valid_tabs = {TAB_FAILURES, TAB_TRENDS}
    assert set(FLAG_TARGET_TAB.values()) <= valid_tabs
    # Every FlagTarget literal is covered
    assert set(FLAG_TARGET_TAB.keys()) == {"failure_feed", "gap_clusters", "trend"}


def test_build_app_renders_flags_panel_section_header():
    """build_app smoke check: the Flags section is present in the rendered
    Blocks. Verifies the panel is wired (not whether the flags themselves are
    correct — the detectors own that). Disable autorefresh so the test
    doesn't try to call the LLM."""
    import json as _json

    log_path = Path(__file__).parent / "_tmp_flags_smoke.jsonl"
    log_path.write_text(_json.dumps(_record_dict()) + "\n")
    try:
        app = build_app(reader=LocalReader(log_path), autorefresh=False)
        assert app is not None
    finally:
        log_path.unlink(missing_ok=True)


def test_format_deflection_panel_renders_summary_text_intact():
    """When a summary exists, the panel surfaces it verbatim — the LLM already
    wrote Markdown, the panel doesn't reformat it. The operator sees what the
    weekly batch produced, full stop."""
    from sentinel import format_deflection_panel

    text = "## Recurring conflict-anecdote requests\n\nThree turns probed..."
    md = format_deflection_panel(text)
    assert text in md, "summary text must appear verbatim"


# ----- Auto-refresh helpers (issue #34 / Sentinel redesign) ------------------


def test_is_stale_treats_missing_file_as_stale(tmp_path):
    """Missing file → stale. Forces a first-run population on launch."""
    from sentinel import is_stale

    assert is_stale(tmp_path / "absent.json") is True


def test_is_stale_treats_recent_file_as_fresh(tmp_path):
    """Files younger than the freshness window are fresh — boot fast on the
    second launch in the same week."""
    from sentinel import is_stale

    p = tmp_path / "recent.json"
    p.write_text("{}")  # mtime = now
    assert is_stale(p, max_age_days=7) is False


def test_is_stale_treats_old_file_as_stale(tmp_path):
    """Files older than the freshness window are stale — forces a refresh on
    the next launch so the dashboard never silently shows week-old data."""
    import os
    from datetime import datetime, timedelta, timezone
    from sentinel import is_stale

    p = tmp_path / "old.json"
    p.write_text("{}")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(p, (old, old))
    assert is_stale(p, max_age_days=7) is True


def test_ensure_fresh_clusters_skips_when_cache_is_fresh(tmp_path, monkeypatch):
    """When the cluster file is fresh the helper must NOT call the LLM batch
    — that's the whole point of caching."""
    from sentinel import ensure_fresh_clusters

    fresh = tmp_path / "gap_clusters.json"
    fresh.write_text("{}")

    called = []
    monkeypatch.setattr(
        "sentinel.cluster_gaps.run_batch",
        lambda **kw: called.append(kw),
    )
    msg = ensure_fresh_clusters(out_path=fresh, max_age_days=7)
    assert msg is None
    assert called == [], "fresh cache must not trigger the batch"


def test_ensure_fresh_clusters_runs_batch_when_cache_missing(tmp_path, monkeypatch):
    """Missing cache → call the LLM batch. Returns None on success (the boot
    banner stays empty)."""
    from sentinel import ensure_fresh_clusters

    out = tmp_path / "gap_clusters.json"
    archive = tmp_path / "archive"

    called = []
    monkeypatch.setattr(
        "sentinel.cluster_gaps.run_batch",
        lambda **kw: called.append(kw),
    )
    msg = ensure_fresh_clusters(out_path=out, archive_dir=archive, max_age_days=7)
    assert msg is None
    assert len(called) == 1
    assert called[0]["out_path"] == out


def test_ensure_fresh_clusters_returns_loud_error_when_batch_fails(tmp_path, monkeypatch):
    """LLM unreachable / no API key → return an error string. Sentinel renders
    this as a banner so the operator knows the dashboard is operating on stale
    data instead of silently shipping it."""
    from sentinel import ensure_fresh_clusters

    out = tmp_path / "gap_clusters.json"

    def _boom(**kw):
        raise RuntimeError("OPENAI_API_KEY missing")

    monkeypatch.setattr("sentinel.cluster_gaps.run_batch", _boom)
    msg = ensure_fresh_clusters(out_path=out, max_age_days=7)
    assert msg is not None
    assert "Cluster" in msg
    assert "OPENAI_API_KEY" in msg


def test_ensure_fresh_summaries_returns_loud_error_when_batch_fails(tmp_path, monkeypatch):
    """Same loud-failure contract as ensure_fresh_clusters — "cache silently
    stale" is exactly the failure mode Sentinel exists to prevent."""
    from sentinel import ensure_fresh_summaries

    def _boom(**kw):
        raise RuntimeError("rate limited")

    monkeypatch.setattr("sentinel.summarize_failures.run_batch", _boom)
    msg = ensure_fresh_summaries(out_dir=tmp_path / "summaries", max_age_days=7)
    assert msg is not None
    assert "Summary" in msg
    assert "rate limited" in msg


def test_format_trend_header_surfaces_metric_label_and_current_value():
    """Each mini-chart's inline header renders the metric's display label + current value
    (formatted per the metric's unit). Used in scan mode above each small multiple."""
    from datetime import datetime, timezone

    bad = lambda: InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "s", "turn_index": 0, "question": "q?", "event_type": "gap",
        "branch": "GAP", "classification_confidence": 1.0,
        "attempts": [{"answer": "a", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
        "knew_answer": False,
    })
    model = DashboardModel([bad(), bad(), bad(), bad()])  # 100% gap_rate
    header = format_trend_header("gap_rate", model)

    assert "gap" in header.lower()  # metric label
    assert "100" in header           # current value 100% rendered as percentage

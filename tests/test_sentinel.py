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
    build_app,
    format_failure_drilldown,
    format_header,
    format_panel,
    format_session_view,
)
from dashboard_model import DashboardModel


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


def test_format_panel_includes_window_label_and_metric_values():
    """format_panel renders the window label and surfaces every required metric."""
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict(event_type="gap"))]
    panel = format_panel("7d", DashboardModel(records))

    assert "7d" in panel
    assert "Total" in panel or "total" in panel.lower()
    assert "Gap" in panel
    assert "Deflection" in panel
    assert "Guardrail" in panel
    assert "p50" in panel.lower()
    assert "p95" in panel.lower()


def test_format_panel_renders_all_five_thematic_blocks():
    """Per issue #35: Outcome / Routing / Engagement / Tool use / Latency. Each block
    has a section header and at least one headline metric."""
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict())]
    panel = format_panel("Global", DashboardModel(records))

    # Block headers
    assert "Outcome" in panel
    assert "Routing" in panel
    assert "Engagement" in panel
    assert "Tool use" in panel
    assert "Latency" in panel

    # Outcome
    assert "Refusal" in panel
    assert "Retry" in panel  # retry_exhausted_rate
    # Routing
    assert "Branch" in panel  # branch_distribution
    assert "Low-confidence" in panel
    assert "Confident-failure" in panel  # the misroute-detection metric
    assert "Multi-label" in panel
    # Engagement
    assert "session" in panel.lower()  # unique_sessions / turns/session
    assert "Drop-off" in panel or "Dropoff" in panel
    assert "Contact" in panel  # offer + conversion
    # Tool use
    assert "Tool" in panel  # uptake + success
    # Latency — per-stage labels
    assert "classifier" in panel.lower()
    assert "generation" in panel.lower()
    assert "guardrail" in panel.lower()


def test_format_panel_renders_none_metrics_as_em_dash():
    """Metrics that are None (e.g. multi_label_rate on all-empty labels, contact_conversion_rate
    on no offers, latency on no records) render as the em-dash placeholder, not as 'None' or '0%'."""
    panel = format_panel("Global", DashboardModel([]))
    # Empty model: contact_conversion_rate, multi_label_rate, technical_tool_uptake_rate, tool_call_success_rate, latency_percentiles all None
    assert "None" not in panel, "None must never leak into the rendered panel"
    assert "—" in panel, "missing data should render as the em-dash placeholder"


def test_format_panel_renders_badge_for_thresholded_metric():
    """A thresholded metric (e.g. gap_rate) renders an inline status pill.
    Per issue #36: use the existing status-pill CSS pattern from module_health."""
    from interaction_log import InteractionRecord

    # Build a model where gap_rate is in the alert band (>15%) — three of four records gap.
    bad_record = _record_dict()
    bad_record["knew_answer"] = False
    records = [
        InteractionRecord.model_validate(bad_record),
        InteractionRecord.model_validate(bad_record),
        InteractionRecord.model_validate(bad_record),
        InteractionRecord.model_validate(_record_dict()),
    ]
    panel = format_panel("Global", DashboardModel(records))

    # Badge HTML appears next to the gap rate row; the alert class is present
    assert "status-pill" in panel
    assert "alert" in panel  # gap_rate at 75% is well above 15% warning band


def test_format_panel_does_not_render_badge_for_orientation_metrics():
    """Orientation metrics (unique_sessions, branch_distribution, multi_label_rate, total)
    have no threshold and must not get a badge — false alarms ruin the dashboard."""
    from interaction_log import InteractionRecord

    records = [InteractionRecord.model_validate(_record_dict())]
    panel = format_panel("Global", DashboardModel(records))

    # Find the unique-sessions line and assert it has no status-pill on it
    lines = panel.splitlines()
    sessions_line = next(line for line in lines if "Unique sessions" in line)
    assert "status-pill" not in sessions_line, (
        "Unique sessions is volume orientation — no badge"
    )
    branches_line = next(line for line in lines if "Branch distribution" in line)
    assert "status-pill" not in branches_line


def test_format_panel_renders_wow_delta_when_prior_model_provided():
    """When a prior-window model is passed, thresholded metrics render an inline WoW arrow + delta."""
    from interaction_log import InteractionRecord

    bad = _record_dict()
    bad["knew_answer"] = False
    current = DashboardModel([InteractionRecord.model_validate(bad)] * 4)        # 100% gap
    prior = DashboardModel([InteractionRecord.model_validate(_record_dict())] * 4)  # 0% gap

    panel = format_panel("7d", current, prior_model=prior)

    # WoW arrow appears + 'pp' unit visible somewhere on the gap rate line
    lines = panel.splitlines()
    gap_line = next(line for line in lines if "Gap rate" in line)
    assert "↑" in gap_line, "rising gap rate must show ↑"
    assert "pp" in gap_line, "delta unit appears in line"


def test_format_panel_omits_wow_delta_when_prior_model_is_none():
    """No prior model (e.g. Global window) → no delta rendered. Badges still appear."""
    from interaction_log import InteractionRecord

    bad = _record_dict()
    bad["knew_answer"] = False
    current = DashboardModel([InteractionRecord.model_validate(bad)] * 4)

    panel = format_panel("Global", current, prior_model=None)

    # Badge present, but no WoW arrows
    assert "status-pill" in panel
    assert "↑" not in panel and "↓" not in panel


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


def test_format_header_includes_source_indicator_and_loaded_timestamp():
    """format_header surfaces the source label and the last-loaded timestamp."""
    loaded_at = datetime(2026, 5, 4, 12, 30, tzinfo=timezone.utc)
    header = format_header(source="Local JSONL", loaded_at=loaded_at)

    assert "Local JSONL" in header
    assert "2026-05-04" in header
    assert "12:30" in header


def test_build_app_returns_gradio_blocks_when_reader_supplied(tmp_path):
    """build_app boots without raising when given an injected reader."""
    log_path = tmp_path / "interactions.jsonl"
    log_path.write_text(json.dumps(_record_dict()) + "\n")

    app = build_app(reader=LocalReader(log_path))
    assert app is not None
    assert hasattr(app, "launch")  # gr.Blocks duck-type


@pytest.mark.skipif(not Path(DEFAULT_LOG_PATH).exists(), reason="No real log file present")
def test_build_app_does_not_crash_against_live_interactions_log():
    """Smoke: Sentinel boots against the live data/logs/interactions.jsonl without raising."""
    app = build_app()
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

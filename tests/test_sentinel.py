"""Sentinel is mostly Gradio glue (cf. app.py exemption in TESTING.md), so
coverage is limited to the small pure helpers + a smoke test that the app
boots against real and synthetic logs without crashing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from interaction_log import DEFAULT_LOG_PATH
from log_reader import LocalReader
from sentinel import build_app, format_header, format_panel
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

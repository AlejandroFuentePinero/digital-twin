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

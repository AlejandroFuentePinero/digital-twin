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
    model = DashboardModel.__call__([])  # type: ignore[call-arg]
    # Use a non-empty model so percentiles are not None.
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

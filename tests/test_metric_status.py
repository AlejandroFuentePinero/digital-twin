"""Threshold + WoW-delta helpers (issue #36).

Pure functions, tested in isolation. Threshold values live as module-level
constants in `metric_status` for easy tuning; tests check both threshold band
behaviour and the inversion logic for higher-is-better metrics.
"""

import pytest

from metric_status import metric_status, wow_delta


def test_lower_is_better_metric_below_healthy_threshold_is_healthy():
    """Per issue #36: gap_rate ≤ 10% → healthy."""
    assert metric_status("gap_rate", 0.05) == "healthy"


def test_lower_is_better_metric_in_warning_band_is_warning():
    """gap_rate above healthy (10%) but ≤ warning (15%) → warning."""
    assert metric_status("gap_rate", 0.12) == "warning"


def test_lower_is_better_metric_above_warning_threshold_is_alert():
    """gap_rate above warning (15%) → alert."""
    assert metric_status("gap_rate", 0.20) == "alert"


def test_lower_is_better_metric_at_healthy_boundary_is_healthy():
    """Boundary inclusive on the healthy side: gap_rate == 0.10 → healthy."""
    assert metric_status("gap_rate", 0.10) == "healthy"


def test_higher_is_better_metric_above_healthy_threshold_is_healthy():
    """TECHNICAL tool-uptake ≥ 70% → healthy. Inversion: 'higher is better'."""
    assert metric_status("technical_tool_uptake_rate", 0.75) == "healthy"


def test_higher_is_better_metric_in_warning_band_is_warning():
    """TECHNICAL tool-uptake between 50% and 70% → warning."""
    assert metric_status("technical_tool_uptake_rate", 0.60) == "warning"


def test_higher_is_better_metric_below_warning_threshold_is_alert():
    """TECHNICAL tool-uptake < 50% → alert."""
    assert metric_status("technical_tool_uptake_rate", 0.30) == "alert"


def test_orientation_metric_returns_none_status():
    """Volume / distribution metrics have no threshold — no badge should render.
    Per issue #36: 'Volume/distribution metrics get no threshold — they're orientation signals.'"""
    assert metric_status("unique_sessions", 64) is None
    assert metric_status("multi_label_rate", 0.0) is None
    assert metric_status("total_interactions", 85) is None


def test_unknown_metric_name_returns_none():
    """Unknown metric → None (don't crash; fail open to no-badge)."""
    assert metric_status("nonexistent_metric", 0.5) is None


def test_none_value_returns_none_status():
    """A metric whose underlying value is None (e.g. empty dataset) gets no badge."""
    assert metric_status("gap_rate", None) is None
    assert metric_status("technical_tool_uptake_rate", None) is None


def test_wow_delta_for_lower_is_better_increase_is_degrading():
    """gap_rate up week-over-week → ↑ arrow + 'degrading' direction (more gaps is worse)."""
    delta = wow_delta("gap_rate", current=0.12, prior=0.08)
    assert delta is not None
    assert delta.delta == pytest.approx(0.04)
    assert delta.arrow == "↑"
    assert delta.direction == "degrading"


def test_wow_delta_for_lower_is_better_decrease_is_improving():
    """gap_rate down week-over-week → ↓ arrow + 'improving' direction."""
    delta = wow_delta("gap_rate", current=0.05, prior=0.10)
    assert delta is not None
    assert delta.delta == pytest.approx(-0.05)
    assert delta.arrow == "↓"
    assert delta.direction == "improving"


def test_wow_delta_for_higher_is_better_increase_is_improving():
    """TECHNICAL tool-uptake up week-over-week → ↑ arrow + 'improving' (more tool use is better)."""
    delta = wow_delta("technical_tool_uptake_rate", current=0.80, prior=0.60)
    assert delta is not None
    assert delta.arrow == "↑"
    assert delta.direction == "improving"


def test_wow_delta_for_higher_is_better_decrease_is_degrading():
    """TECHNICAL tool-uptake down → ↓ arrow + 'degrading'."""
    delta = wow_delta("technical_tool_uptake_rate", current=0.40, prior=0.65)
    assert delta is not None
    assert delta.arrow == "↓"
    assert delta.direction == "degrading"


def test_wow_delta_unchanged_value_is_stable_with_horizontal_arrow():
    """current == prior → → arrow + 'stable'. No misleading sign on noise."""
    delta = wow_delta("gap_rate", current=0.10, prior=0.10)
    assert delta is not None
    assert delta.delta == 0
    assert delta.arrow == "→"
    assert delta.direction == "stable"


def test_wow_delta_returns_none_when_either_value_missing():
    """current=None or prior=None → no delta. Avoids fabricating signal from absent priors
    (e.g. first run where there's no prior week)."""
    assert wow_delta("gap_rate", current=0.10, prior=None) is None
    assert wow_delta("gap_rate", current=None, prior=0.10) is None
    assert wow_delta("gap_rate", current=None, prior=None) is None


def test_wow_delta_returns_none_for_orientation_metrics():
    """Orientation metrics get no delta — no badge AND no arrow. Unique sessions changing
    is information about traffic, not health."""
    assert wow_delta("unique_sessions", current=64, prior=50) is None
    assert wow_delta("multi_label_rate", current=0.0, prior=0.0) is None


def test_wow_delta_unit_matches_threshold_unit():
    """Delta carries the metric's natural unit ('pp' for rates, 'ms' for latency).
    Drives display formatting in the panel."""
    rate_delta = wow_delta("gap_rate", current=0.12, prior=0.08)
    assert rate_delta.unit == "pp"
    latency_delta = wow_delta("latency_p95_total", current=30_000, prior=20_000)
    assert latency_delta.unit == "ms"


def test_every_thresholded_metric_is_documented_in_sentinel_md():
    """Forcing function: every metric with a threshold must appear in docs/SENTINEL.md.
    Catches the 'added a metric, forgot to document it' drift. Per issue #36 AC: doc is
    the single source of truth for 'what does this metric mean'."""
    from pathlib import Path

    from metric_status import THRESHOLDS

    sentinel_md = Path(__file__).resolve().parents[1] / "docs" / "SENTINEL.md"
    assert sentinel_md.exists(), "docs/SENTINEL.md must exist (issue #36 deliverable)"
    text = sentinel_md.read_text()

    # All four required section headings present
    assert "## Per-metric reference" in text
    assert "## Trace runbooks" in text
    assert "## Engagement caveats" in text
    assert "## Operational caveats" in text

    # Every thresholded metric must be referenced by name
    missing = [name for name in THRESHOLDS.keys() if name not in text]
    assert not missing, (
        f"Thresholded metrics missing from docs/SENTINEL.md: {missing}. "
        "Add a per-metric section under '## Per-metric reference'."
    )

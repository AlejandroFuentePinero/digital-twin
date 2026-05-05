"""Threshold (Tier A) + shift-status (Tier B) + WoW-delta helpers (issue #36;
post-#48 tier polish).

Pure functions, tested in isolation. Threshold values live as module-level
constants in `metric_status` for easy tuning; tests check both threshold band
behaviour and the inversion logic for higher-is-better metrics, plus the new
shift-status bands for Tier B metrics.
"""

import pytest

from metric_status import (
    SHIFT_ALERT,
    SHIFT_WARNING,
    THRESHOLDS,
    TIER_B_METRICS,
    metric_status,
    shift_status,
    tier_of,
    wow_delta,
)


# ----- Tier A: metric_status (value-on-band) --------------------------------


def test_lower_is_better_metric_below_healthy_threshold_is_healthy():
    """refusal_rate ≤ 1% → healthy. (Tier A — mechanism IS failure.)"""
    assert metric_status("refusal_rate", 0.005) == "healthy"


def test_lower_is_better_metric_in_warning_band_is_warning():
    """refusal_rate above healthy (1%) but ≤ warning (3%) → warning."""
    assert metric_status("refusal_rate", 0.02) == "warning"


def test_lower_is_better_metric_above_warning_threshold_is_alert():
    """refusal_rate above warning (3%) → alert."""
    assert metric_status("refusal_rate", 0.05) == "alert"


def test_lower_is_better_metric_at_healthy_boundary_is_healthy():
    """Boundary inclusive on the healthy side: refusal_rate == 0.01 → healthy."""
    assert metric_status("refusal_rate", 0.01) == "healthy"


def test_higher_is_better_metric_above_healthy_threshold_is_healthy():
    """contact_conversion_rate ≥ 10% → healthy. Inversion: 'higher is better'."""
    assert metric_status("contact_conversion_rate", 0.15) == "healthy"


def test_higher_is_better_metric_in_warning_band_is_warning():
    """contact_conversion_rate between 5% and 10% → warning."""
    assert metric_status("contact_conversion_rate", 0.07) == "warning"


def test_higher_is_better_metric_below_warning_threshold_is_alert():
    """contact_conversion_rate < 5% → alert."""
    assert metric_status("contact_conversion_rate", 0.02) == "alert"


def test_orientation_metric_returns_none_status():
    """Tier C / unregistered metrics have no value threshold — no badge.
    Post-#48 the only metrics in THRESHOLDS are Tier A; Tier B and Tier C
    both return None from metric_status."""
    assert metric_status("unique_sessions", 64) is None
    assert metric_status("gap_rate", 0.10) is None  # Tier B post-#48
    assert metric_status("total_interactions", 85) is None


def test_unknown_metric_name_returns_none():
    """Unknown metric → None (don't crash; fail open to no-badge)."""
    assert metric_status("nonexistent_metric", 0.5) is None


def test_none_value_returns_none_status():
    """A metric whose underlying value is None (e.g. empty dataset) gets no badge."""
    assert metric_status("refusal_rate", None) is None
    assert metric_status("contact_conversion_rate", None) is None


# ----- Tier B: shift_status (relative-change-on-band) -----------------------


def test_shift_status_below_warning_band_is_healthy():
    """Relative change <7% → healthy. The metric moved but not enough to
    surface as a behavioural shift."""
    # 5% relative change (0.10 → 0.105)
    assert shift_status(0.105, 0.10) == "healthy"


def test_shift_status_in_warning_band_is_warning():
    """Relative change ≥7% but <15% → warning. Worth a glance."""
    # 10% relative change (0.10 → 0.11)
    assert shift_status(0.11, 0.10) == "warning"


def test_shift_status_above_alert_band_is_alert():
    """Relative change ≥15% → alert. Behavioural shift worth investigation."""
    # 20% relative change (0.10 → 0.12)
    assert shift_status(0.12, 0.10) == "alert"


def test_shift_status_is_direction_agnostic():
    """A 20% drop is just as alertable as a 20% rise — the metric's polarity
    isn't known at this layer (Tier B metrics don't have one). Direction
    interpretation is the operator's job."""
    assert shift_status(0.08, 0.10) == "alert"  # 20% drop
    assert shift_status(0.12, 0.10) == "alert"  # 20% rise


def test_shift_status_at_band_boundaries_is_inclusive():
    """Boundary inclusive on the higher-severity side: exactly 7% → warning,
    exactly 15% → alert. Uses integer-friendly values to avoid floating-
    point drift on the ratio computation."""
    # exactly 7% relative change (107 vs 100 → ratio 1.07 exactly)
    assert shift_status(107, 100) == "warning"
    # exactly 15% relative change (115 vs 100 → ratio 1.15 exactly)
    assert shift_status(115, 100) == "alert"


def test_shift_status_returns_none_when_either_value_missing():
    """No prior-window data → no shift; Sentinel renders no badge."""
    assert shift_status(None, 0.10) is None
    assert shift_status(0.10, None) is None
    assert shift_status(None, None) is None


def test_shift_status_returns_none_when_prior_is_zero():
    """Avoid division-by-zero. A metric jumping from 0 to anything is
    structurally a 100% relative change of nothing — surface as 'no
    comparison available' rather than always-alert."""
    assert shift_status(0.05, 0.0) is None


def test_shift_status_constants_are_sensible():
    """Document the constants so a future tuning session has the values pinned."""
    assert SHIFT_WARNING == 0.07
    assert SHIFT_ALERT == 0.15


# ----- tier_of --------------------------------------------------------------


def test_tier_of_returns_a_for_thresholded_metrics():
    assert tier_of("refusal_rate") == "A"
    assert tier_of("retry_exhausted_rate") == "A"
    assert tier_of("contact_conversion_rate") == "A"
    assert tier_of("tool_call_success_rate") == "A"
    assert tier_of("latency_p95_total") == "A"


def test_tier_of_returns_b_for_shift_tracked_metrics():
    assert tier_of("gap_rate") == "B"
    assert tier_of("deflection_rate") == "B"
    assert tier_of("answered_with_substance_rate") == "B"


def test_tier_of_returns_c_for_unregistered_metrics():
    """Tier C is implicit — anything not Tier A and not Tier B falls through
    to no-badge treatment. Volume metrics (total_interactions,
    unique_sessions, tool_call_count) are explicitly orientation-only."""
    assert tier_of("unique_sessions") == "C"
    assert tier_of("nonexistent_metric") == "C"


def test_tier_a_and_tier_b_membership_are_disjoint():
    """A metric can't be both — value-on-band and shift-on-band would
    double-surface in the banner. This guards against a future edit
    accidentally registering a metric in both."""
    assert not (set(THRESHOLDS) & TIER_B_METRICS)


# ----- WoW delta (existing) --------------------------------------------------


def test_wow_delta_for_lower_is_better_increase_is_degrading():
    """refusal_rate up week-over-week → ↑ arrow + 'degrading' direction."""
    delta = wow_delta("refusal_rate", current=0.04, prior=0.01)
    assert delta is not None
    assert delta.delta == pytest.approx(0.03)
    assert delta.arrow == "↑"
    assert delta.direction == "degrading"


def test_wow_delta_for_lower_is_better_decrease_is_improving():
    """refusal_rate down week-over-week → ↓ arrow + 'improving' direction."""
    delta = wow_delta("refusal_rate", current=0.005, prior=0.02)
    assert delta is not None
    assert delta.arrow == "↓"
    assert delta.direction == "improving"


def test_wow_delta_for_higher_is_better_increase_is_improving():
    """contact_conversion_rate up week-over-week → ↑ arrow + 'improving'."""
    delta = wow_delta("contact_conversion_rate", current=0.18, prior=0.10)
    assert delta is not None
    assert delta.arrow == "↑"
    assert delta.direction == "improving"


def test_wow_delta_for_higher_is_better_decrease_is_degrading():
    """contact_conversion_rate down → ↓ arrow + 'degrading'."""
    delta = wow_delta("contact_conversion_rate", current=0.04, prior=0.12)
    assert delta is not None
    assert delta.arrow == "↓"
    assert delta.direction == "degrading"


def test_wow_delta_unchanged_value_is_stable_with_horizontal_arrow():
    """current == prior → → arrow + 'stable'. No misleading sign on noise."""
    delta = wow_delta("refusal_rate", current=0.01, prior=0.01)
    assert delta is not None
    assert delta.delta == 0
    assert delta.arrow == "→"
    assert delta.direction == "stable"


def test_wow_delta_returns_none_when_either_value_missing():
    """current=None or prior=None → no delta. Avoids fabricating signal from
    absent priors (e.g. first run where there's no prior week)."""
    assert wow_delta("refusal_rate", current=0.01, prior=None) is None
    assert wow_delta("refusal_rate", current=None, prior=0.01) is None
    assert wow_delta("refusal_rate", current=None, prior=None) is None


def test_wow_delta_returns_none_for_orientation_metrics():
    """Tier B / Tier C metrics get no Tier-A-style delta — they don't have
    a polarity (improving/degrading direction). Tier B uses shift_status
    instead; Tier C is bare-number orientation."""
    assert wow_delta("unique_sessions", current=64, prior=50) is None
    assert wow_delta("gap_rate", current=0.10, prior=0.05) is None  # Tier B post-#48


def test_wow_delta_unit_matches_threshold_unit():
    """Delta carries the metric's natural unit ('pp' for rates, 'ms' for
    latency). Drives display formatting in the panel."""
    rate_delta = wow_delta("refusal_rate", current=0.04, prior=0.01)
    assert rate_delta.unit == "pp"
    latency_delta = wow_delta("latency_p95_total", current=30_000, prior=20_000)
    assert latency_delta.unit == "ms"


def test_every_thresholded_metric_is_documented_in_sentinel_md():
    """Forcing function: every Tier A metric (everything in THRESHOLDS) must
    appear in docs/SENTINEL.md. Catches the 'added a metric, forgot to
    document it' drift."""
    from pathlib import Path

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

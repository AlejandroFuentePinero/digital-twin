"""Per-metric thresholds + shift-status + week-over-week deltas — Sentinel's
observability amplifier (issue #36; tier framework refactor 2026-05-05).

Pure functions over scalar metric values. Sentinel pulls metric numbers off
`DashboardModel`, then asks `metric_status` (Tier A) or `shift_status`
(Tier B) for a badge, and `wow_delta` for a trend arrow. No coupling to
`DashboardModel` itself — the contract is just
``(metric_name, value) → status`` (Tier A) and
``(current, prior) → status`` (Tier B).

**Three-tier framework** (see docs/audits/observability-tier-polish.md):

- **Tier A — Mechanism IS failure.** Value crossing a band IS the failure
  event. Threshold lookup in `THRESHOLDS`; `metric_status(metric, value)` is
  the entry point. Alerts page-at-3am.
- **Tier B — Behavioural shift.** No value threshold; relative shift across
  window pairs (7d↔30d, 30d↔90d) drives the badge. Membership in
  `TIER_B_METRICS`; `shift_status(current, prior)` is the entry point.
  Bands `SHIFT_WARNING=0.07`, `SHIFT_ALERT=0.15` (relative absolute change).
- **Tier C — Deterministic reflection.** Pure system state; no badge ever.
  Implicit: any metric not in `THRESHOLDS` and not in `TIER_B_METRICS`.

Threshold values come from the issue #36 spec table + Session 47 polish;
sources include eval R2 baselines, live-log inventory (Session 28), and
LIMITATIONS register entries. Tunable via the `THRESHOLDS` constant —
re-import sentinel to pick up changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["healthy", "warning", "alert"]
Tier = Literal["A", "B", "C"]

# Tier B shift bands — relative absolute change between two window values.
# Placeholders per PRD #41 § Open questions deferred — recalibrate after a
# month of operator usage shows where the noise / signal line sits.
SHIFT_WARNING = 0.07
SHIFT_ALERT = 0.15


@dataclass(frozen=True)
class Threshold:
    """Per-metric threshold band.

    For ``higher_is_better=False`` (default, lower-is-better):
        value ≤ healthy → "healthy"
        healthy < value ≤ warning → "warning"
        value > warning → "alert"

    For ``higher_is_better=True``:
        value ≥ healthy → "healthy"
        warning ≤ value < healthy → "warning"
        value < warning → "alert"
    """
    healthy: float
    warning: float
    higher_is_better: bool = False
    unit: Literal["pp", "ms", ""] = "pp"


# Tier A — Mechanism IS failure. Threshold band on value drives the badge;
# crossing a band is itself the failure event (page-at-3am).
THRESHOLDS: dict[str, Threshold] = {
    "refusal_rate":             Threshold(healthy=0.01, warning=0.03),
    "retry_exhausted_rate":     Threshold(healthy=0.03, warning=0.05),
    "contact_conversion_rate":  Threshold(healthy=0.10, warning=0.05, higher_is_better=True),
    "tool_call_success_rate":   Threshold(healthy=0.99, warning=0.95, higher_is_better=True),
    "latency_p95_total":        Threshold(healthy=25_000, warning=40_000, unit="ms"),
}

# Tier B — Behavioural shift. No value threshold; the badge fires on
# relative change between window pairs (handled by `shift_status` + the
# Sentinel row-renderer in `_row_severity`). Membership only — band values
# are the global SHIFT_WARNING / SHIFT_ALERT constants above.
#
# Pre-#48 (the polish before this) several of these carried value thresholds
# in THRESHOLDS that didn't structurally interpret as health (gap_rate
# healthy ≤10% was calibrated against a pre-#42 proxy that under-counted
# gaps; honest post-#42 gap rate predicted at ~44% on healthy traffic). The
# right framing is shift-on-shape, not value-on-shape.
TIER_B_METRICS: frozenset[str] = frozenset({
    "gap_rate",
    "deflection_rate",
    "guardrail_rejection_rate",
    "low_confidence_rate",
    "mean_classification_confidence",
    "mean_turns_per_session",
    "turns_per_session_median",
    "contact_offer_rate",
    "technical_tool_call_rate",
    "answered_with_substance_rate",
})


def tier_of(metric_name: str) -> Tier | None:
    """Return the metric's tier, or None when the metric is unknown.

    Tier C is implicit: any metric in METRIC_GETTERS that isn't in
    THRESHOLDS and isn't in TIER_B_METRICS. We don't enumerate Tier C
    explicitly because the runtime treatment is just 'no badge', which is
    the default fall-through."""
    if metric_name in THRESHOLDS:
        return "A"
    if metric_name in TIER_B_METRICS:
        return "B"
    # Anything else (unregistered, or registered Tier C) gets no badge.
    return "C"


def shift_status(current: float | None, prior: float | None) -> Status | None:
    """Tier B status driver: classify relative absolute change between two
    window values.

    Returns ``"alert"`` at ≥SHIFT_ALERT (15%) relative change in either
    direction, ``"warning"`` at ≥SHIFT_WARNING (7%), ``"healthy"`` below.
    Returns ``None`` when either input is missing or `prior` is zero (no
    meaningful relative comparison)."""
    if current is None or prior is None or prior == 0:
        return None
    rel = abs(current - prior) / abs(prior)
    if rel >= SHIFT_ALERT:
        return "alert"
    if rel >= SHIFT_WARNING:
        return "warning"
    return "healthy"


def metric_status(metric_name: str, value: float | None) -> Status | None:
    """Classify ``value`` against ``metric_name``'s threshold band.

    Returns None for: orientation metrics (no threshold), unknown metrics, or
    None inputs. The Sentinel UI renders no badge for None — no false alarms
    on metrics that aren't load-bearing for health.
    """
    if value is None:
        return None
    threshold = THRESHOLDS.get(metric_name)
    if threshold is None:
        return None
    if threshold.higher_is_better:
        if value >= threshold.healthy:
            return "healthy"
        if value >= threshold.warning:
            return "warning"
        return "alert"
    if value <= threshold.healthy:
        return "healthy"
    if value <= threshold.warning:
        return "warning"
    return "alert"


@dataclass(frozen=True)
class WoWDelta:
    """Week-over-week change for a thresholded metric.

    `delta` is the raw difference (current - prior) in the metric's natural
    unit (rates as fractions, latency as ms). `arrow` is a glyph for the
    panel; `direction` interprets the change against the metric's polarity
    so the operator doesn't need to remember whether ↑ is good or bad per
    metric.
    """
    delta: float
    arrow: Literal["↑", "↓", "→"]
    direction: Literal["improving", "degrading", "stable"]
    unit: Literal["pp", "ms", ""]


def wow_delta(metric_name: str, current: float | None, prior: float | None) -> WoWDelta | None:
    """Return the WoW delta for a thresholded metric, or None.

    None when:
    - The metric has no threshold (orientation signals — no direction polarity).
    - Either input is None (no prior week → no delta to fabricate).
    """
    if current is None or prior is None:
        return None
    threshold = THRESHOLDS.get(metric_name)
    if threshold is None:
        return None

    diff = current - prior
    if diff == 0:
        return WoWDelta(delta=0, arrow="→", direction="stable", unit=threshold.unit)
    rising = diff > 0
    if rising:
        direction = "improving" if threshold.higher_is_better else "degrading"
    else:
        direction = "degrading" if threshold.higher_is_better else "improving"
    return WoWDelta(
        delta=diff,
        arrow="↑" if rising else "↓",
        direction=direction,
        unit=threshold.unit,
    )

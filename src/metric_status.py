"""Per-metric thresholds + week-over-week deltas — Sentinel's observability
amplifier (issue #36).

Pure functions over scalar metric values. Sentinel pulls metric numbers off
`DashboardModel`, then asks `metric_status` for a badge and `wow_delta` for a
trend arrow. No coupling to `DashboardModel` itself — the contract is just
``(metric_name, value) → status`` and ``(metric_name, current, prior) → delta``.

Threshold values come from the issue #36 spec table; sources include eval R2
baselines, live-log inventory (Session 28), and LIMITATIONS register entries.
Tunable via the `THRESHOLDS` constant — re-import sentinel to pick up changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["healthy", "warning", "alert"]


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


# Threshold table — issue #36. Sources noted per metric. Tune by editing here.
THRESHOLDS: dict[str, Threshold] = {
    # Outcome — KB / guardrail / loop signals
    "gap_rate": Threshold(healthy=0.10, warning=0.15),
    "deflection_rate": Threshold(healthy=0.05, warning=0.10),
    "refusal_rate": Threshold(healthy=0.01, warning=0.03),
    "guardrail_rejection_rate": Threshold(healthy=0.15, warning=0.25),
    "retry_exhausted_rate": Threshold(healthy=0.03, warning=0.05),
    # Routing
    "low_confidence_rate": Threshold(healthy=0.10, warning=0.20),
    "confident_failure_rate": Threshold(healthy=0.03, warning=0.07),
    # Latency — only the headline (total p95)
    "latency_p95_total": Threshold(healthy=25_000, warning=40_000, unit="ms"),
    # Higher-is-better metrics.
    # NB: ``technical_tool_call_rate`` (renamed from ``technical_tool_uptake_rate``
    # in PRD #41 slice 3) is orientation-only — no threshold. The denominator
    # (`all TECHNICAL`) includes turns that legitimately don't need a tool call
    # — meta-questions about the system, generic skills questions, follow-ups
    # whose context is already in scope. Post-#45 the canary surface measures
    # outcome quality directly (`outcome_accuracy` / `keyword_coverage` /
    # `red_flag_rate`); the live metric stays a coarse aggregate by design.
    "contact_conversion_rate": Threshold(healthy=0.10, warning=0.05, higher_is_better=True),
    "turns_per_session_median": Threshold(healthy=2.0, warning=1.5, higher_is_better=True, unit=""),
}


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

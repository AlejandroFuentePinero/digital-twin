"""Local Gradio dashboard over the canonical interaction log (Phase 4).

Three-tab layout (broad → specific): Metrics → Trends → Failures. The Metrics
tab carries the Flags panel + a 3-windowed box-in-box overview (7d / 30d /
Global, leftmost = most recent). The Trends tab carries the Trend Explorer
(scan + investigate). The Failures tab carries the Failure Feed plus the cached
Gap Clusters and Deflection Summary panels.

On launch the cluster + summary batches are auto-refreshed when their cached
file is missing or older than ``DEFAULT_FRESHNESS_DAYS``; failures surface as a
visible warning banner rather than crashing the app.

Run locally with ``uv run python src/sentinel.py``.
"""

from __future__ import annotations

import html
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import gradio as gr
import pandas as pd

from branches import REGISTRY as BRANCH_REGISTRY
from cluster_gaps import (
    DEFAULT_ARCHIVE_DIR as CLUSTERS_ARCHIVE_DIR,
    DEFAULT_OUT_PATH as CLUSTERS_DEFAULT_PATH,
    read_cluster_history,
    read_clusters,
)
import cluster_gaps
import summarize_failures
from dashboard_model import METRIC_GETTERS, DashboardModel
from flag_detector import (
    Flag,
    detect_gap_rate_jump,
    detect_new_cluster,
    detect_repeat_failure,
)
from summarize_failures import DEFAULT_SUMMARIES_DIR, latest_summary_path, read_summary
from failure_feed import (
    FAILURE_MODES,
    FailureRow,
    Session,
    classify_failure,
    group_by_session,
    select_failures,
)
from interaction_log import InteractionRecord
from log_reader import HFReader, LocalReader, LogReader
from metric_status import THRESHOLDS, WoWDelta, metric_status, wow_delta


# Leftmost column = most recent. Operator opens Sentinel to check "what happened
# this week" first; broad context (Global) sits to the right as reference.
WINDOWS = [("7d", 7), ("30d", 30), ("Global", None)]

# Branch dropdown choices in Failure Feed; "All" prefixes the canonical branch list.
BRANCH_CHOICES = ["All", *BRANCH_REGISTRY.keys()]
FAILURE_MODE_CHOICES = ["All", *FAILURE_MODES]
FEED_TABLE_HEADERS = ["date", "branch", "failure mode", "question", "attempts", "confidence"]

# Auto-refresh cadence — matches the documented weekly batch cadence so any
# launch sees data at most one cadence stale.
DEFAULT_FRESHNESS_DAYS = 7

# Smoothing window for the trend chart's rolling-average line. Chosen to keep
# day-to-day noise readable without over-smoothing weekly seasonality.
ROLLING_AVG_DAYS = 3

# Tab identifiers so flag-click handlers can switch tabs by ID.
TAB_METRICS = "tab-metrics"
TAB_TRENDS = "tab-trends"
TAB_FAILURES = "tab-failures"

# FlagDetector targets → Sentinel tab IDs. Clicking a flag's Investigate button
# selects the matching tab on the gr.Tabs component.
FLAG_TARGET_TAB: dict[str, str] = {
    "failure_feed": TAB_FAILURES,
    "gap_clusters": TAB_FAILURES,
    "trend": TAB_TRENDS,
}


SENTINEL_CSS = """
.status-pill {
    display: inline-block;
    font-size: 0.72em; font-weight: 700; letter-spacing: 0.05em;
    padding: 2px 7px; border-radius: 4px;
    margin: 0 4px;
    text-transform: uppercase;
}
.status-pill.healthy { background: rgba(34, 197, 94, 0.18); color: #22c55e; }
.status-pill.warning { background: rgba(251, 146, 60, 0.16); color: #fb923c; }
.status-pill.alert   { background: rgba(248, 113, 113, 0.18); color: #f87171; }

.metric-value.healthy { color: #22c55e; font-weight: 600; }
.metric-value.warning { color: #fb923c; font-weight: 600; }
.metric-value.alert   { color: #f87171; font-weight: 600; }

.wow-delta {
    display: inline-block;
    font-size: 0.78em;
    margin-left: 4px;
    color: #94a3b8;
}
.wow-delta.improving { color: #22c55e; }
.wow-delta.degrading { color: #f87171; }
.wow-delta.stable    { color: #94a3b8; }

.window-card {
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 14px 16px;
    background: rgba(30, 41, 59, 0.35);
}
.window-card .window-card-title {
    font-size: 1.05em; font-weight: 700;
    margin-bottom: 10px;
    border-bottom: 1px solid #334155; padding-bottom: 6px;
}
.metric-card {
    border: 1px solid #1f2937;
    border-radius: 6px;
    padding: 8px 10px;
    margin: 8px 0;
    background: rgba(15, 23, 42, 0.45);
}
.metric-card .metric-card-title {
    font-size: 0.78em; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #94a3b8;
    margin-bottom: 4px;
}
.metric-card ul { margin: 0; padding-left: 1.1em; }
.metric-card li { margin: 2px 0; }

.flag-card {
    border-left: 3px solid #f87171;
    padding: 8px 12px;
    margin: 6px 0;
    background: rgba(248, 113, 113, 0.06);
    border-radius: 3px;
}
.flag-card .flag-headline { font-weight: 600; color: #f87171; }
.flag-card .flag-detail   { font-size: 0.88em; color: #cbd5e1; margin-top: 2px; }

.refresh-banner {
    border-left: 3px solid #fb923c;
    padding: 6px 10px;
    margin: 6px 0;
    background: rgba(251, 146, 60, 0.08);
    color: #fb923c;
    border-radius: 3px;
    font-size: 0.88em;
}
"""


# ---- Reader bootstrap -------------------------------------------------------


def _default_reader() -> LogReader:
    if os.environ.get("HF_WRITE_TOKEN"):
        return HFReader()
    return LocalReader()


def _source_label(reader: LogReader) -> str:
    return "HF Dataset" if isinstance(reader, HFReader) else "Local JSONL"


# ---- Date / number formatters ----------------------------------------------


EM_DASH = "—"


def _fmt_date(value) -> str:
    """Date-only render (``YYYY-MM-DD``) for any ISO timestamp / datetime / date.

    Sentinel deliberately drops time-of-day everywhere — the dashboard is a
    daily-cadence operator surface, not a live trace. Time-of-day adds noise
    and visual clutter without informing decisions made at this granularity.
    """
    if value is None:
        return EM_DASH
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    # ISO-8601 string (`2026-05-04T12:34:56+00:00`) — split off the date prefix.
    return str(value)[:10]


def format_header(source: str, loaded_at: datetime) -> str:
    return f"**Source:** {source}  ·  **Loaded:** {_fmt_date(loaded_at)}"


def _fmt_pct(rate: float | None) -> str:
    return EM_DASH if rate is None else f"{rate * 100:.1f}%"


def _fmt_ms(ms: float | None) -> str:
    return EM_DASH if ms is None else f"{ms:.0f} ms"


def _fmt_num(n: float | None, ndigits: int = 1) -> str:
    return EM_DASH if n is None else f"{n:.{ndigits}f}"


def _fmt_branches(distribution: dict[str, float]) -> str:
    if not distribution:
        return EM_DASH
    parts = sorted(distribution.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{branch} {fraction * 100:.0f}%" for branch, fraction in parts)


def _fmt_dropoff(dropoff: dict[int, int]) -> str:
    if not dropoff:
        return EM_DASH
    parts = sorted(dropoff.items())
    return " · ".join(f"t{idx}:{count}" for idx, count in parts)


def _fmt_latency_row(p: dict[int, float | None]) -> str:
    return f"p50 {_fmt_ms(p.get(50))} / p95 {_fmt_ms(p.get(95))}"


# ---- Threshold-aware value rendering ---------------------------------------


def _badge(metric_name: str | None, value: float | None) -> str:
    """Inline status pill HTML, or empty string when no threshold applies."""
    if metric_name is None:
        return ""
    status = metric_status(metric_name, value)
    if status is None:
        return ""
    return f'<span class="status-pill {status}">{status}</span>'


def _value_span(metric_name: str | None, value: float | None, value_str: str) -> str:
    """Wrap the value in a CSS-classed span so healthy values render green,
    warning orange, alert red — matches the badge colour for at-a-glance
    readability."""
    if metric_name is None:
        return value_str
    status = metric_status(metric_name, value)
    if status is None:
        return value_str
    return f'<span class="metric-value {status}">{value_str}</span>'


def _delta(metric_name: str | None, current: float | None, prior: float | None) -> str:
    """Inline WoW arrow + delta HTML, or empty string when no prior or no threshold."""
    if metric_name is None or prior is None:
        return ""
    delta = wow_delta(metric_name, current, prior)
    if delta is None:
        return ""
    return _format_delta_span(delta)


def _format_delta_span(delta: WoWDelta) -> str:
    if delta.unit == "pp":
        magnitude = f"{abs(delta.delta) * 100:.1f}pp"
    elif delta.unit == "ms":
        magnitude = f"{abs(delta.delta):.0f}ms"
    else:
        magnitude = f"{abs(delta.delta):.1f}"
    if delta.direction == "stable":
        body = f"{delta.arrow} 0{delta.unit if delta.unit else ''}"
    else:
        body = f"{delta.arrow} {magnitude}"
    return f'<span class="wow-delta {delta.direction}">{body}</span>'


def _row(
    label: str,
    value_str: str,
    metric_name: str | None = None,
    raw_value: float | None = None,
    prior_value: float | None = None,
) -> str:
    """Render one metric row: ``- **label:** <coloured-value> badge delta``."""
    coloured = _value_span(metric_name, raw_value, value_str)
    badge = _badge(metric_name, raw_value)
    delta = _delta(metric_name, raw_value, prior_value)
    return f"<li><b>{label}:</b> {coloured}{badge}{delta}</li>"


# ---- Per-window panel (box-in-box) ------------------------------------------


def _block_card(title: str, rows: list[str]) -> str:
    inner = "".join(rows)
    return (
        f"<div class='metric-card'>"
        f"<div class='metric-card-title'>{title}</div>"
        f"<ul>{inner}</ul>"
        f"</div>"
    )


def format_panel(
    label: str,
    model: DashboardModel,
    prior_model: DashboardModel | None = None,
) -> str:
    """Render one window's full health panel as a bordered card containing five
    inner cards (Outcome / Routing / Engagement / Tool use / Latency)."""

    def _prior(getter):
        return getter(prior_model) if prior_model is not None else None

    outcome = [
        _row("Total interactions", str(model.total_interactions)),
        _row(
            "Gap rate", _fmt_pct(model.gap_rate),
            metric_name="gap_rate", raw_value=model.gap_rate,
            prior_value=_prior(lambda m: m.gap_rate),
        ),
        _row(
            "Deflection rate", _fmt_pct(model.deflection_rate),
            metric_name="deflection_rate", raw_value=model.deflection_rate,
            prior_value=_prior(lambda m: m.deflection_rate),
        ),
        _row(
            "Refusal rate", _fmt_pct(model.refusal_rate),
            metric_name="refusal_rate", raw_value=model.refusal_rate,
            prior_value=_prior(lambda m: m.refusal_rate),
        ),
        _row(
            "Guardrail rejection rate", _fmt_pct(model.guardrail_rejection_rate),
            metric_name="guardrail_rejection_rate", raw_value=model.guardrail_rejection_rate,
            prior_value=_prior(lambda m: m.guardrail_rejection_rate),
        ),
        _row(
            "Retry-exhaustion rate", _fmt_pct(model.retry_exhausted_rate),
            metric_name="retry_exhausted_rate", raw_value=model.retry_exhausted_rate,
            prior_value=_prior(lambda m: m.retry_exhausted_rate),
        ),
    ]

    routing = [
        _row("Branch distribution", _fmt_branches(model.branch_distribution)),
        _row(
            "Low-confidence rate (<0.7)", _fmt_pct(model.low_confidence_rate()),
            metric_name="low_confidence_rate", raw_value=model.low_confidence_rate(),
            prior_value=_prior(lambda m: m.low_confidence_rate()),
        ),
        _row(
            "Confident-failure rate (≥0.8 & failed)", _fmt_pct(model.confident_failure_rate()),
            metric_name="confident_failure_rate", raw_value=model.confident_failure_rate(),
            prior_value=_prior(lambda m: m.confident_failure_rate()),
        ),
        _row("Multi-label rate", _fmt_pct(model.multi_label_rate)),
    ]

    engagement = [
        _row("Unique sessions", str(model.unique_sessions)),
        _row(
            "Turns/session (median)", _fmt_num(model.turns_per_session_median),
            metric_name="turns_per_session_median", raw_value=model.turns_per_session_median,
            prior_value=_prior(lambda m: m.turns_per_session_median),
        ),
        _row("Drop-off by turn", _fmt_dropoff(model.dropoff_by_turn)),
        _row("Contact-offer rate", _fmt_pct(model.contact_offer_rate)),
        _row(
            "Contact-conversion rate", _fmt_pct(model.contact_conversion_rate),
            metric_name="contact_conversion_rate", raw_value=model.contact_conversion_rate,
            prior_value=_prior(lambda m: m.contact_conversion_rate),
        ),
    ]

    tool = [
        _row(
            "Tool uptake (TECHNICAL)", _fmt_pct(model.technical_tool_uptake_rate),
            metric_name="technical_tool_uptake_rate", raw_value=model.technical_tool_uptake_rate,
            prior_value=_prior(lambda m: m.technical_tool_uptake_rate),
        ),
        _row("Tool-call success rate", _fmt_pct(model.tool_call_success_rate)),
    ]

    total_p95 = model.latency_percentiles("total").get(95)
    total_p95_prior = _prior(lambda m: m.latency_percentiles("total").get(95))
    latency = [
        _row("classifier", _fmt_latency_row(model.latency_percentiles("classifier"))),
        _row("retrieval", _fmt_latency_row(model.latency_percentiles("retrieval"))),
        _row("generation", _fmt_latency_row(model.latency_percentiles("generation"))),
        _row("guardrail", _fmt_latency_row(model.latency_percentiles("guardrail"))),
        _row(
            "total", _fmt_latency_row(model.latency_percentiles("total")),
            metric_name="latency_p95_total", raw_value=total_p95, prior_value=total_p95_prior,
        ),
    ]

    blocks = (
        _block_card("Outcome", outcome)
        + _block_card("Routing", routing)
        + _block_card("Engagement", engagement)
        + _block_card("Tool use", tool)
        + _block_card("Latency (per stage)", latency)
    )
    return (
        f"<div class='window-card'>"
        f"<div class='window-card-title'>{label}</div>"
        f"{blocks}"
        f"</div>"
    )


# ---- Failure Feed -----------------------------------------------------------


def _failure_table_rows(rows: list[FailureRow]) -> list[list]:
    """Convert FailureRow list to gr.Dataframe-friendly 2D list (one row per failure)."""
    return [
        [
            _fmt_date(row.timestamp),
            row.branch,
            row.failure_mode,
            row.question,
            row.attempt_count,
            f"{row.classification_confidence:.2f}",
        ]
        for row in rows
    ]


def format_failure_drilldown(record: InteractionRecord) -> str:
    """Markdown rendering of every per-attempt + per-chunk + tool-call + latency field
    needed to debug 'what failed and why' for a single turn."""
    labels = ", ".join(record.classifier_labels) if record.classifier_labels else EM_DASH
    parts: list[str] = [
        "**Question:** " + record.question,
        f"**Branch:** `{record.branch}`  ·  **Classifier labels:** `{labels}`  "
        f"·  **Confidence:** {record.classification_confidence:.2f}  ·  **Event:** `{record.event_type}`",
        f"**Date:** {_fmt_date(record.timestamp)}",
        "",
        "**Attempts:**",
    ]
    for i, attempt in enumerate(record.attempts):
        ok = attempt.get("is_acceptable", True)
        badge = "PASS" if ok else "FAIL"
        parts.append(f"- *Attempt {i}* — **{badge}**")
        parts.append(f"    - **answer:** {attempt.get('answer', '')}")
        parts.append(f"    - **guardrail_feedback:** {attempt.get('guardrail_feedback', '')}")
    parts.append("")
    parts.append("**Retrieved chunks:**")
    if not record.retrieved_chunks:
        parts.append("- _none_")
    else:
        for c in record.retrieved_chunks:
            parts.append(
                f"- `{c.get('source_file', '')}` · {c.get('section_heading', '')}"
            )
    parts.append("")
    parts.append("**Tool calls:**")
    if not record.tool_calls:
        parts.append("- _none_")
    else:
        for c in record.tool_calls:
            parts.append(
                f"- `{c.get('name', '')}` · args={c.get('args', {})} · status={c.get('status', '')}"
            )
    parts.append("")
    lat = record.latency_ms
    parts.append("**Latency (ms):**")
    parts.append(
        f"- classifier {lat.get('classifier', 0)} · retrieval {lat.get('retrieval', 0)} "
        f"· generation {lat.get('generation', 0)} · guardrail {lat.get('guardrail', 0)} "
        f"· **total {lat.get('total', 0)}**"
    )
    return "\n".join(parts)


def _turn_summary(record: InteractionRecord) -> str:
    """One-line summary line for the per-turn `<details><summary>` row in the session view."""
    mode = classify_failure(record)
    badge = "PASS" if mode is None else f"FAIL · {mode}"
    truncated = record.question[:80] + ("…" if len(record.question) > 80 else "")
    return (
        f"<b>Turn {record.turn_index}</b> · {record.branch} · {record.event_type} · "
        f"{html.escape(truncated)} <i>[{badge}]</i>"
    )


def format_session_view(session: Session) -> str:
    """Per-session view: header + one ``<details>`` per turn whose body is the drilldown."""
    contact_bits = []
    if session.contact_offered:
        contact_bits.append("offered")
    if session.contact_provided:
        contact_bits.append("provided")
    contact_str = ", ".join(contact_bits) if contact_bits else "neither"
    parts = [
        f"### Session `{session.session_id}`",
        f"**Turns:** {session.turn_count}  ·  **Contact:** {contact_str}  "
        f"·  **Total latency:** {session.total_latency_ms} ms",
        "",
    ]
    for r in session.records:
        body = format_failure_drilldown(r)
        parts.append(
            f"<details>\n<summary>{_turn_summary(r)}</summary>\n\n{body}\n\n</details>\n"
        )
    return "\n".join(parts)


# ---- Cluster + Deflection panels --------------------------------------------


CLUSTER_EMPTY_PLACEHOLDER = (
    "_No cached gap clusters yet. Auto-refresh skipped (no gap turns in window, "
    "or LLM unavailable)._"
)
DEFLECTION_EMPTY_PLACEHOLDER = (
    "_No cached deflection summary yet. Auto-refresh skipped (no deflection turns "
    "in window, or LLM unavailable)._"
)


def format_cluster_panel(data: dict | None) -> str:
    """Render the Cluster panel from a `gap_clusters.json` dict."""
    if data is None:
        return CLUSTER_EMPTY_PLACEHOLDER
    clusters = data.get("clusters", [])
    if not clusters:
        return (
            f"_No clusters in the last {data.get('period_days', '?')} days "
            "(no gap turns, or all groups below the minimum size)._"
        )
    parts = [
        f"_Generated {_fmt_date(data.get('generated_at'))} · "
        f"window {data.get('period_days', '?')}d_",
        "",
    ]
    for cluster in clusters:
        parts.append(f"- **{cluster['label']}** · count {cluster['count']}")
        for example in cluster.get("examples", []):
            parts.append(f"    - {example}")
    return "\n".join(parts)


def format_deflection_panel(text: str | None) -> str:
    """Render the latest deflection summary; placeholder when absent."""
    if text is None:
        return DEFLECTION_EMPTY_PLACEHOLDER
    return text


# ---- Flags panel ------------------------------------------------------------


FLAGS_EMPTY_PLACEHOLDER = (
    "_No anomalies detected — every detector returned no flags. Stable / quiet "
    "weeks render no flags by design._"
)


def format_flags_summary(flags: list[Flag]) -> str:
    """Markdown render of every flag's headline + detail (no per-flag click handlers
    here; the Investigate buttons are separate gr.Button instances built in
    `_render_flags`)."""
    if not flags:
        return FLAGS_EMPTY_PLACEHOLDER
    cards: list[str] = []
    for flag in flags:
        headline = html.escape(flag.headline)
        detail = html.escape(flag.detail)
        cards.append(
            "<div class='flag-card'>"
            f"<div class='flag-headline'>{headline}</div>"
            f"<div class='flag-detail'>{detail}</div>"
            "</div>"
        )
    return "\n".join(cards)


def _build_flags(model: DashboardModel) -> list[Flag]:
    """Run all three detectors against the live data + cached cluster files."""
    return [
        *detect_gap_rate_jump(model.records),
        *detect_new_cluster(
            read_clusters(CLUSTERS_DEFAULT_PATH),
            read_cluster_history(CLUSTERS_ARCHIVE_DIR),
        ),
        *detect_repeat_failure(model.records),
    ]


# ---- Trend Explorer (chart helpers) -----------------------------------------


METRIC_LABELS: dict[str, str] = {
    "gap_rate": "Gap rate",
    "deflection_rate": "Deflection rate",
    "refusal_rate": "Refusal rate",
    "guardrail_rejection_rate": "Guardrail rejection rate",
    "retry_exhausted_rate": "Retry-exhaustion rate",
    "low_confidence_rate": "Low-confidence rate (<0.7)",
    "confident_failure_rate": "Confident-failure rate (≥0.8 & failed)",
    "latency_p95_total": "Total latency p95",
    "technical_tool_uptake_rate": "Tool uptake (TECHNICAL)",
    "contact_conversion_rate": "Contact-conversion rate",
    "turns_per_session_median": "Turns/session (median)",
}

THEMATIC_BLOCKS: dict[str, list[str]] = {
    "Outcome": [
        "gap_rate", "deflection_rate", "refusal_rate",
        "guardrail_rejection_rate", "retry_exhausted_rate",
    ],
    "Routing": ["low_confidence_rate", "confident_failure_rate"],
    "Engagement": ["turns_per_session_median", "contact_conversion_rate"],
    "Tool use": ["technical_tool_uptake_rate"],
    "Latency": ["latency_p95_total"],
}

TREND_WINDOWS: list[tuple[str, int | None]] = [
    ("7d", 7), ("30d", 30), ("90d", 90), ("All-time", None),
]

# Explicit colour mapping so threshold lines are readable + match the rest of
# the dashboard. Healthy = green (per operator directive); warning = amber.
CHART_COLOR_MAP = {
    "actual":     "#94a3b8",  # slate-400 — low-saturation raw daily values
    "3-day avg":  "#3b82f6",  # blue-500  — primary smoothed trend
    "healthy":    "#22c55e",  # green-500 — healthy threshold reference line
    "warning":    "#f59e0b",  # amber-500 — warning threshold reference line
    "prior":      "#a855f7",  # purple-500 — prior-period overlay (investigate)
}


def _y_axis_title(metric: str) -> str:
    """Per-metric Y-axis title — the user-readable unit, not the column name.

    Replaces the previous (misleading) ``"value"`` axis label that didn't tell
    the operator what they were reading."""
    label = METRIC_LABELS.get(metric, metric)
    threshold = THRESHOLDS.get(metric)
    if threshold is None:
        return label
    if threshold.unit == "pp":
        return f"{label} (%)"
    if threshold.unit == "ms":
        return f"{label} (ms)"
    return label


def _scale_value(metric: str, value: float | None) -> float | None:
    """Convert raw fractions to percentages for plotting (so the Y-axis can
    render '9.4%' instead of '0.094'). Latency and counts pass through."""
    if value is None:
        return None
    threshold = THRESHOLDS.get(metric)
    if threshold is not None and threshold.unit == "pp":
        return value * 100
    return value


def _fmt_metric_value(metric: str, value: float | None) -> str:
    """Header value formatter (un-scaled — these go into markdown headers, not charts)."""
    threshold = THRESHOLDS.get(metric)
    if threshold is None:
        return _fmt_num(value)
    if threshold.unit == "pp":
        return _fmt_pct(value)
    if threshold.unit == "ms":
        return _fmt_ms(value)
    return _fmt_num(value)


def chart_dataframe(
    model: DashboardModel,
    metric: str,
    days: int | None,
    *,
    prior_model: DashboardModel | None = None,
) -> pd.DataFrame:
    """Long-format DataFrame for ``gr.LinePlot``.

    Columns: ``date`` (datetime), ``value`` (float), ``series`` (str).

    Series:
    - ``"actual"`` — raw daily values, low-saturation reference.
    - ``"3-day avg"`` — centered rolling average, primary trend line.
    - ``"healthy"`` / ``"warning"`` — horizontal threshold reference lines.
    - ``"prior"`` (when ``prior_model`` supplied) — prior-period overlay,
      shifted forward by ``days`` so it overlays the current window.

    All rate values are scaled to percentages (×100) so the Y-axis reads in
    units the operator expects.

    Empty model → empty DataFrame (chart layer renders nothing).
    """
    series = model.time_series_by_day(metric, days=days)
    if not series:
        return pd.DataFrame(columns=["date", "value", "series"])

    raw = pd.DataFrame(series, columns=["date", "value"])
    raw["date"] = pd.to_datetime(raw["date"])
    raw["value"] = raw["value"].apply(lambda v: _scale_value(metric, v))

    rolling = raw["value"].rolling(window=ROLLING_AVG_DAYS, center=True, min_periods=1).mean()

    rows: list[dict] = []
    for d, v in zip(raw["date"], raw["value"]):
        if pd.notna(v):
            rows.append({"date": d, "value": float(v), "series": "actual"})
    for d, v in zip(raw["date"], rolling):
        if pd.notna(v):
            rows.append({"date": d, "value": float(v), "series": "3-day avg"})

    threshold = THRESHOLDS.get(metric)
    if threshold is not None and len(raw):
        first = raw["date"].iloc[0]
        last = raw["date"].iloc[-1]
        healthy = _scale_value(metric, threshold.healthy)
        warning = _scale_value(metric, threshold.warning)
        rows.extend([
            {"date": first, "value": float(healthy), "series": "healthy"},
            {"date": last, "value": float(healthy), "series": "healthy"},
            {"date": first, "value": float(warning), "series": "warning"},
            {"date": last, "value": float(warning), "series": "warning"},
        ])

    if prior_model is not None and days is not None:
        prior_series = prior_model.time_series_by_day(metric, days=days)
        for d, v in prior_series:
            if v is None:
                continue
            shifted = pd.to_datetime(d) + pd.Timedelta(days=days)
            rows.append({
                "date": shifted, "value": float(_scale_value(metric, v)),
                "series": "prior",
            })

    return pd.DataFrame(rows)


def format_trend_header(
    metric: str,
    model: DashboardModel,
    prior_model: DashboardModel | None = None,
) -> str:
    """Inline markdown header above each mini chart: label · coloured value · badge · WoW arrow."""
    label = METRIC_LABELS.get(metric, metric)
    value = METRIC_GETTERS[metric](model)
    value_str = _fmt_metric_value(metric, value)
    coloured = _value_span(metric, value, value_str)
    badge = _badge(metric, value)
    prior_value = METRIC_GETTERS[metric](prior_model) if prior_model is not None else None
    delta = _delta(metric, value, prior_value)
    return f"**{label}:** {coloured} {badge}{delta}"


# ---- Auto-refresh of cached cluster + summary files -------------------------


def is_stale(path: Path, max_age_days: int = DEFAULT_FRESHNESS_DAYS) -> bool:
    """True when ``path`` is missing or older than ``max_age_days``.

    Used by the auto-refresh helpers to decide whether to invoke the LLM
    batch. Missing → stale (forces first-run population); old → stale
    (forces weekly refresh). Anything younger is considered fresh."""
    path = Path(path)
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime < datetime.now(timezone.utc) - timedelta(days=max_age_days)


def _run_with_capture(label: str, fn) -> str | None:
    """Run ``fn``; return ``None`` on success or a one-line error message on
    failure. Sentinel surfaces the message in the page banner — silent stale
    cache is exactly the kind of failure mode Sentinel exists to prevent."""
    try:
        fn()
        return None
    except Exception as exc:
        return f"⚠ {label} batch failed: {type(exc).__name__}: {exc}"


def ensure_fresh_clusters(
    log_path: Path | None = None,
    out_path: Path = CLUSTERS_DEFAULT_PATH,
    archive_dir: Path | None = CLUSTERS_ARCHIVE_DIR,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
) -> str | None:
    """Run ``cluster_gaps.run_batch`` only when the cached file is stale."""
    if not is_stale(out_path, max_age_days):
        return None
    return _run_with_capture(
        "Cluster",
        lambda: cluster_gaps.run_batch(
            days=cluster_gaps.BATCH_DEFAULT_DAYS,
            out_path=out_path,
            log_path=log_path,
            archive_dir=archive_dir,
        ),
    )


def ensure_fresh_summaries(
    log_path: Path | None = None,
    out_dir: Path = DEFAULT_SUMMARIES_DIR,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
) -> str | None:
    """Run ``summarize_failures.run_batch`` only when the latest deflection
    summary is stale (deflection is the only group surfaced in Sentinel; the
    other two groups are written for offline reading)."""
    latest = latest_summary_path("deflection", out_dir)
    if latest is not None and not is_stale(latest, max_age_days):
        return None
    return _run_with_capture(
        "Summary",
        lambda: summarize_failures.run_batch(
            days=summarize_failures.BATCH_DEFAULT_DAYS,
            out_dir=out_dir,
            log_path=log_path,
        ),
    )


def _autorefresh_banner(messages: list[str | None]) -> str:
    """Render any non-None refresh failure as a visible banner; empty when all
    runs succeeded (or were skipped because the cache was fresh)."""
    real = [m for m in messages if m]
    if not real:
        return ""
    inner = "<br>".join(html.escape(m) for m in real)
    return f"<div class='refresh-banner'>{inner}</div>"


# ---- App boot helpers -------------------------------------------------------


def _load(reader: LogReader) -> tuple[DashboardModel, datetime]:
    return DashboardModel(reader.read()), datetime.now(timezone.utc)


def _render_panels(model: DashboardModel) -> list[str]:
    return [
        format_panel(label, model.for_window(days=days), prior_model=model.for_prior_window(days=days))
        for label, days in WINDOWS
    ]


def _filter_records(reader: LogReader, window_label: str) -> list[InteractionRecord]:
    days = dict(WINDOWS).get(window_label)
    return DashboardModel(reader.read()).for_window(days=days).records


# ---- build_app --------------------------------------------------------------


def build_app(reader: LogReader | None = None, *, autorefresh: bool = True) -> gr.Blocks:
    reader = reader or _default_reader()
    source = _source_label(reader)

    # Auto-run the cluster + summary batches when their cached files are
    # missing or older than DEFAULT_FRESHNESS_DAYS. Failures degrade gracefully
    # — Sentinel still boots, the panel falls back to whatever cache exists,
    # and the banner surfaces the failure message.
    refresh_messages: list[str | None] = []
    if autorefresh:
        refresh_messages = [ensure_fresh_clusters(), ensure_fresh_summaries()]

    model, loaded_at = _load(reader)
    initial_failures = select_failures(model.records)

    with gr.Blocks(title="Digital Twin · Sentinel", css=SENTINEL_CSS) as app:
        with gr.Row():
            gr.Markdown("# Digital Twin · Sentinel")
            refresh_btn = gr.Button("↻ Refresh", variant="secondary", size="sm", scale=0)
        header_md = gr.Markdown(format_header(source, loaded_at))
        banner_md = gr.Markdown(_autorefresh_banner(refresh_messages))

        with gr.Tabs() as tabs:
            # ---- Metrics tab ----------------------------------------------
            with gr.Tab("Metrics", id=TAB_METRICS):
                gr.Markdown("## Flags")
                flags_md = gr.Markdown(format_flags_summary(_build_flags(model)))

                # Per-flag Investigate buttons live in their own row below the
                # summary so each can wire its own tab-switch handler.
                flag_button_rows: list[gr.Row] = []
                flag_buttons: list[tuple[gr.Button, str]] = []

                # Build buttons up to a reasonable cap; rebuild on Refresh by
                # toggling visibility / re-labelling. Three flag types max in
                # practice — capped at 6 to allow for repeat_failure firing on
                # multiple distinct questions.
                MAX_FLAGS_RENDERED = 6
                with gr.Row():
                    for _ in range(MAX_FLAGS_RENDERED):
                        btn = gr.Button("", visible=False, size="sm", variant="secondary")
                        flag_buttons.append((btn, ""))

                gr.Markdown("## Health overview")
                with gr.Row():
                    panel_components: list[gr.Markdown] = []
                    for panel_md in _render_panels(model):
                        with gr.Column():
                            panel_components.append(gr.Markdown(panel_md))

            # ---- Trends tab -----------------------------------------------
            with gr.Tab("Trends", id=TAB_TRENDS):
                gr.Markdown("## Trend Explorer")

                selected_metric = gr.State(None)
                scan_buttons: dict[str, gr.Button] = {}
                scan_charts: dict[str, gr.LinePlot] = {}
                scan_headers: dict[str, gr.Markdown] = {}

                with gr.Column(visible=True) as scan_view:
                    for block_name, block_metrics in THEMATIC_BLOCKS.items():
                        gr.Markdown(f"### {block_name}")
                        with gr.Row():
                            for metric in block_metrics:
                                with gr.Column(min_width=240):
                                    scan_headers[metric] = gr.Markdown(
                                        format_trend_header(metric, model)
                                    )
                                    scan_charts[metric] = gr.LinePlot(
                                        value=chart_dataframe(model, metric, days=30),
                                        x="date", y="value", color="series",
                                        x_title="Date",
                                        y_title=_y_axis_title(metric),
                                        color_map=CHART_COLOR_MAP,
                                        height=160, show_label=False,
                                    )
                                    scan_buttons[metric] = gr.Button(
                                        f"Investigate {METRIC_LABELS[metric]} ↗",
                                        size="sm", variant="secondary",
                                    )

                with gr.Column(visible=False) as investigate_view:
                    investigate_title = gr.Markdown("")
                    with gr.Row():
                        window_radio = gr.Radio(
                            choices=[label for label, _ in TREND_WINDOWS],
                            value="30d", label="Window", scale=1,
                        )
                        prior_chk = gr.Checkbox(
                            label="Show prior period", value=False, scale=0,
                        )
                    investigate_chart = gr.LinePlot(
                        value=pd.DataFrame(columns=["date", "value", "series"]),
                        x="date", y="value", color="series",
                        x_title="Date", y_title="value",
                        color_map=CHART_COLOR_MAP,
                        height=460, show_label=False,
                    )
                    back_to_scan_btn = gr.Button("← Back to scan", variant="secondary")

            # ---- Failures tab ---------------------------------------------
            with gr.Tab("Failures", id=TAB_FAILURES):
                gr.Markdown("## Failure Feed")
                with gr.Row():
                    branch_dd = gr.Dropdown(
                        choices=BRANCH_CHOICES, value="All", label="Branch", scale=1
                    )
                    mode_dd = gr.Dropdown(
                        choices=FAILURE_MODE_CHOICES, value="All", label="Failure mode", scale=1
                    )
                    window_dd = gr.Dropdown(
                        choices=[label for label, _ in WINDOWS], value="Global",
                        label="Window", scale=1,
                    )
                    search_in = gr.Textbox(value="", label="Search question", scale=2)

                rows_state = gr.State(initial_failures)
                selected_session_id = gr.State(None)

                with gr.Column(visible=True) as feed_view:
                    failures_df = gr.Dataframe(
                        headers=FEED_TABLE_HEADERS,
                        value=_failure_table_rows(initial_failures),
                        interactive=False, wrap=True,
                    )
                    drilldown_md = gr.Markdown(
                        "_Select a row above to see the per-turn drilldown._"
                    )
                    view_session_btn = gr.Button("View full session", interactive=False)

                with gr.Column(visible=False) as session_view:
                    session_md = gr.Markdown("")
                    back_btn = gr.Button("← Back to feed")

                gr.Markdown("---\n## Gap Clusters")
                cluster_md = gr.Markdown(
                    format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH))
                )

                gr.Markdown("---\n## Deflection summary")
                deflection_md = gr.Markdown(
                    format_deflection_panel(read_summary("deflection", DEFAULT_SUMMARIES_DIR))
                )

        # ---- Wiring ---------------------------------------------------------

        def _flag_button_updates(flags: list[Flag]):
            """Build button-update tuples for the MAX_FLAGS_RENDERED slot grid."""
            updates = []
            for i in range(MAX_FLAGS_RENDERED):
                if i < len(flags):
                    f = flags[i]
                    updates.append(gr.update(
                        visible=True,
                        value=f"Investigate · {f.kind} ↗",
                    ))
                else:
                    updates.append(gr.update(visible=False, value=""))
            return updates

        # Initial flag-button population
        initial_flag_targets: list[str] = [
            FLAG_TARGET_TAB.get(f.target, TAB_METRICS) for f in _build_flags(model)
        ]
        # Pad with empty string sentinels so each slot has a target lookup.
        initial_flag_targets += [""] * (MAX_FLAGS_RENDERED - len(initial_flag_targets))
        flag_targets_state = gr.State(initial_flag_targets)

        # Apply visibility for the initial render
        for i, btn_pair in enumerate(flag_buttons):
            btn = btn_pair[0]
            if i < len(initial_flag_targets) and initial_flag_targets[i]:
                btn.visible = True
                btn.value = f"Investigate · flag {i + 1} ↗"

        # ---- Refresh: reload disk + re-render every panel + auto-refresh batches
        def _refresh(branch, mode, window_label, search):
            cluster_msg = ensure_fresh_clusters() if autorefresh else None
            summary_msg = ensure_fresh_summaries() if autorefresh else None
            new_model, new_loaded_at = _load(reader)
            records = new_model.for_window(days=dict(WINDOWS).get(window_label)).records
            failure_rows = select_failures(
                records, branch=branch, failure_mode=mode, question_search=search
            )
            flags = _build_flags(new_model)
            flag_targets = [FLAG_TARGET_TAB.get(f.target, TAB_METRICS) for f in flags]
            flag_targets += [""] * (MAX_FLAGS_RENDERED - len(flag_targets))
            return [
                format_header(source, new_loaded_at),
                _autorefresh_banner([cluster_msg, summary_msg]),
                format_flags_summary(flags),
                *_flag_button_updates(flags),
                flag_targets,
                *_render_panels(new_model),
                _failure_table_rows(failure_rows),
                failure_rows,
                "_Select a row above to see the per-turn drilldown._",
                None,
                gr.update(interactive=False),
                format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH)),
                format_deflection_panel(read_summary("deflection", DEFAULT_SUMMARIES_DIR)),
            ]

        flag_button_components = [b for b, _ in flag_buttons]
        refresh_btn.click(
            fn=_refresh,
            inputs=[branch_dd, mode_dd, window_dd, search_in],
            outputs=[
                header_md, banner_md,
                flags_md,
                *flag_button_components,
                flag_targets_state,
                *panel_components,
                failures_df, rows_state, drilldown_md,
                selected_session_id, view_session_btn,
                cluster_md, deflection_md,
            ],
        )

        # ---- Flag-click handlers: switch to the target tab
        def _make_flag_click(slot_index: int):
            def _handler(targets):
                target = targets[slot_index] if slot_index < len(targets) else ""
                if not target:
                    return gr.update()
                return gr.Tabs(selected=target)
            return _handler

        for i, (btn, _) in enumerate(flag_buttons):
            btn.click(
                fn=_make_flag_click(i),
                inputs=[flag_targets_state],
                outputs=[tabs],
            )

        # ---- Failure feed filter changes
        def _refresh_feed(branch, mode, window_label, search):
            records = _filter_records(reader, window_label)
            rows = select_failures(
                records, branch=branch, failure_mode=mode, question_search=search
            )
            return (
                _failure_table_rows(rows),
                rows,
                "_Select a row above to see the per-turn drilldown._",
                None,
                gr.update(interactive=False),
            )

        for control in (branch_dd, mode_dd, window_dd, search_in):
            control.change(
                fn=_refresh_feed,
                inputs=[branch_dd, mode_dd, window_dd, search_in],
                outputs=[
                    failures_df, rows_state, drilldown_md,
                    selected_session_id, view_session_btn,
                ],
            )

        # ---- Failure-feed row select → drilldown
        def _on_row_select(rows: list[FailureRow], evt: gr.SelectData):
            if not rows or evt.index is None:
                return "", None, gr.update(interactive=False)
            row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
            if row_idx >= len(rows):
                return "", None, gr.update(interactive=False)
            row = rows[row_idx]
            return (
                format_failure_drilldown(row.record),
                row.record.session_id,
                gr.update(interactive=True),
            )

        failures_df.select(
            fn=_on_row_select,
            inputs=[rows_state],
            outputs=[drilldown_md, selected_session_id, view_session_btn],
        )

        # ---- View full session / back
        def _show_session(session_id: str | None):
            if not session_id:
                return gr.update(), gr.update(), gr.update()
            sessions = group_by_session(reader.read())
            match = next((s for s in sessions if s.session_id == session_id), None)
            if match is None:
                return gr.update(), gr.update(), gr.update()
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                format_session_view(match),
            )

        view_session_btn.click(
            fn=_show_session,
            inputs=[selected_session_id],
            outputs=[feed_view, session_view, session_md],
        )

        def _back_to_feed():
            return gr.update(visible=True), gr.update(visible=False)

        back_btn.click(fn=_back_to_feed, outputs=[feed_view, session_view])

        # ---- Trend Explorer: investigate-mode renderer
        def _build_investigate_chart(metric, window_label, show_prior):
            if not metric:
                return gr.update(), pd.DataFrame(columns=["date", "value", "series"])
            days = dict(TREND_WINDOWS).get(window_label, 30)
            current_records = DashboardModel(reader.read())
            prior = current_records.for_prior_window(days=days) if show_prior else None
            df = chart_dataframe(current_records, metric, days=days, prior_model=prior)
            title = (
                f"### Investigating: {METRIC_LABELS.get(metric, metric)}\n"
                + format_trend_header(metric, current_records, prior_model=prior)
            )
            return title, df

        def _enter_investigate_for(metric: str):
            def _handler(window_label, show_prior):
                title, df = _build_investigate_chart(metric, window_label, show_prior)
                return (
                    metric,
                    gr.update(visible=False),
                    gr.update(visible=True),
                    title,
                    gr.update(value=df, y_title=_y_axis_title(metric)),
                )
            return _handler

        for metric, btn in scan_buttons.items():
            btn.click(
                fn=_enter_investigate_for(metric),
                inputs=[window_radio, prior_chk],
                outputs=[
                    selected_metric, scan_view, investigate_view,
                    investigate_title, investigate_chart,
                ],
            )

        def _refresh_investigate(metric, window_label, show_prior):
            title, df = _build_investigate_chart(metric, window_label, show_prior)
            y_title = _y_axis_title(metric) if metric else "value"
            return title, gr.update(value=df, y_title=y_title)

        for control in (window_radio, prior_chk):
            control.change(
                fn=_refresh_investigate,
                inputs=[selected_metric, window_radio, prior_chk],
                outputs=[investigate_title, investigate_chart],
            )

        def _back_to_scan():
            return gr.update(visible=True), gr.update(visible=False)

        back_to_scan_btn.click(
            fn=_back_to_scan, outputs=[scan_view, investigate_view]
        )

    return app


if __name__ == "__main__":
    build_app().launch(inbrowser=True)

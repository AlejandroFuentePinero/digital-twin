"""Local Gradio dashboard over the canonical interaction log (Phase 4).

Three-tab layout (broad → specific): Metrics → Trends → Failures.

The Metrics tab opens with a status banner (`SENTINEL · N alerts · N
warnings · N healthy`) followed by Flags and a single-header Health Overview
where each metric row shows three windowed values inline (7d / 30d / Global)
with divergence highlighting when the windows disagree.

The Trends tab carries the Trend Explorer (scan + investigate). The Failures
tab carries the Failure Feed (one collapsible accordion per row, expanding
in place) plus the cached Gap Clusters and Deflection Summary panels.

On launch the cluster + summary batches auto-refresh when their cached file
is missing or older than ``DEFAULT_FRESHNESS_DAYS``; failures surface as a
visible warning banner rather than crashing the app.

Visual language is *Midnight Mono*: near-black background, monospace for
data, sans-serif for prose, restrained accent colours, no gradients or
shadows.

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
HEADLINE_WINDOW_DAYS = 7  # Drives the status-banner counters

# Branch dropdown choices in Failure Feed.
BRANCH_CHOICES = ["All", *BRANCH_REGISTRY.keys()]
FAILURE_MODE_CHOICES = ["All", *FAILURE_MODES]

# Auto-refresh cadence — matches the documented weekly batch cadence so any
# launch sees data at most one cadence stale.
DEFAULT_FRESHNESS_DAYS = 7

# Smoothing window for the trend chart's rolling-average line.
ROLLING_AVG_DAYS = 3

# Tab identifiers so flag-click handlers can switch tabs by ID.
TAB_METRICS = "tab-metrics"
TAB_TRENDS = "tab-trends"
TAB_FAILURES = "tab-failures"

FLAG_TARGET_TAB: dict[str, str] = {
    "failure_feed": TAB_FAILURES,
    "gap_clusters": TAB_FAILURES,
    "trend": TAB_TRENDS,
}

# Failure-feed expansion cap — number of pre-allocated gr.Accordion slots.
# 30 covers the realistic upper bound (~17 failures in the live log today).
MAX_FEED_ROWS = 30

# Flag-button slot cap. Three detector kinds; up to 6 covers repeat_failure
# firing on multiple distinct questions.
MAX_FLAGS_RENDERED = 6


# ---- Midnight Mono CSS ------------------------------------------------------


SENTINEL_CSS = """
:root {
    --bg-base:       #0a0a0a;
    --bg-surface:    #171717;
    --text-primary:  #fafafa;
    --text-secondary:#a3a3a3;
    --text-muted:    #525252;
    --border:        #262626;
    --healthy:       #4ade80;
    --warning:       #fbbf24;
    --alert:         #f87171;
    --divergence:    #818cf8;
}

body, .gradio-container {
    background: var(--bg-base) !important;
    color: var(--text-primary);
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    font-weight: 400;
}

/* Monospace for data */
.mono, code, .metric-value, .status-counts, .feed-meta, .threshold-caption {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-feature-settings: "tnum" on, "lnum" on;
}

/* ---- Status banner ---- */
.status-banner {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px 16px;
    margin: 6px 0 14px;
}
.status-banner .status-title {
    font-weight: 500;
    letter-spacing: 0.06em;
    font-size: 0.78em;
    text-transform: uppercase;
    color: var(--text-secondary);
    margin-right: 12px;
}
.status-banner .status-counts span {
    margin-right: 14px;
    font-weight: 500;
}
.status-counts .count-alert    { color: var(--alert); }
.status-counts .count-warning  { color: var(--warning); }
.status-counts .count-healthy  { color: var(--healthy); }
.status-banner .status-list {
    margin-top: 6px;
    font-size: 0.92em;
    color: var(--text-secondary);
}
.status-banner .status-list .label {
    color: var(--text-muted);
    margin-right: 6px;
}
.status-banner details { margin-top: 4px; }
.status-banner details summary {
    color: var(--text-muted); cursor: pointer; font-size: 0.85em;
    list-style: none;
}
.status-banner details summary::-webkit-details-marker { display: none; }

/* ---- Section block (Metrics) ---- */
.section-block {
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-surface);
    padding: 10px 14px;
    margin: 8px 0;
}
.section-title {
    font-size: 0.78em; font-weight: 500;
    letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px; margin-bottom: 8px;
}
.metric-grid {
    display: grid;
    grid-template-columns: 1.6fr repeat(3, 1fr) 1fr;
    column-gap: 14px; row-gap: 4px;
    align-items: baseline;
}
.metric-grid .col-header {
    font-size: 0.72em; font-weight: 500;
    color: var(--text-muted);
    letter-spacing: 0.08em; text-transform: uppercase;
    padding-bottom: 2px;
    border-bottom: 1px solid var(--border);
}
.metric-grid .col-header.numeric { text-align: right; }
.metric-grid .metric-label { color: var(--text-primary); }
.metric-grid .metric-value {
    text-align: right;
    color: var(--text-primary);
    padding: 1px 6px;
    border-radius: 2px;
}
.metric-grid .metric-value.healthy { color: var(--healthy); }
.metric-grid .metric-value.warning { color: var(--warning); }
.metric-grid .metric-value.alert   { color: var(--alert); }
.metric-grid .metric-value.divergent {
    border: 1px solid var(--divergence);
}
.metric-grid .metric-suffix {
    color: var(--text-muted);
    font-size: 0.85em;
}

/* ---- Flags ---- */
.flag-card {
    border: 1px solid var(--border);
    border-left: 3px solid var(--alert);
    border-radius: 3px;
    background: var(--bg-surface);
    padding: 8px 12px;
    margin: 4px 0;
}
.flag-card .flag-headline { font-weight: 500; color: var(--alert); }
.flag-card .flag-detail   { font-size: 0.88em; color: var(--text-secondary); margin-top: 2px; }

/* ---- Refresh banner (LLM batch failure) ---- */
.refresh-banner {
    border: 1px solid var(--warning);
    border-left: 3px solid var(--warning);
    background: var(--bg-surface);
    color: var(--warning);
    border-radius: 3px;
    padding: 6px 10px; margin: 6px 0;
    font-size: 0.88em;
}

/* ---- Failure feed ---- */
.feed-row {
    border: 1px solid var(--border);
    border-radius: 3px;
    background: var(--bg-surface);
    margin: 4px 0;
}
.feed-row summary {
    list-style: none; cursor: pointer;
    padding: 8px 12px;
    display: grid;
    grid-template-columns: 100px 110px 150px 1fr 60px 60px;
    column-gap: 14px; align-items: baseline;
}
.feed-row summary::-webkit-details-marker { display: none; }
.feed-row .feed-meta { color: var(--text-secondary); }
.feed-row .feed-mode {
    text-transform: uppercase; font-size: 0.8em;
    letter-spacing: 0.04em;
}
.feed-row .feed-mode.refused             { color: var(--alert); }
.feed-row .feed-mode.gap                 { color: var(--warning); }
.feed-row .feed-mode.retry-exhausted     { color: var(--warning); }
.feed-row .feed-mode.rejected-then-recovered { color: var(--text-secondary); }
.feed-row .feed-q { color: var(--text-primary); }
.feed-row .feed-num { color: var(--text-secondary); text-align: right; }
.feed-row[open] summary { border-bottom: 1px solid var(--border); }
.feed-row .feed-body { padding: 10px 14px; color: var(--text-primary); }

.feed-empty {
    padding: 18px; text-align: center;
    color: var(--text-muted); font-style: italic;
}

/* ---- Charts: caption styling ---- */
.threshold-caption {
    color: var(--text-muted);
    font-size: 0.82em;
    margin-top: 2px;
}

/* Restraint: no shadows, no gradients, small radii everywhere */
button { border-radius: 6px !important; }
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
    """Date-only render (``YYYY-MM-DD``) for any ISO timestamp / datetime / date."""
    if value is None:
        return EM_DASH
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
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


# ---- Threshold-aware rendering helpers --------------------------------------


def _status_class(metric_name: str | None, value: float | None) -> str:
    """CSS class for the metric value cell — drives the colour treatment."""
    if metric_name is None:
        return ""
    return metric_status(metric_name, value) or ""


def _delta_inline(metric_name: str | None, current, prior) -> str:
    """Compact inline delta arrow (post-value), or empty string when no delta applies."""
    if metric_name is None or prior is None:
        return ""
    delta = wow_delta(metric_name, current, prior)
    if delta is None:
        return ""
    if delta.unit == "pp":
        magnitude = f"{abs(delta.delta) * 100:.1f}pp"
    elif delta.unit == "ms":
        magnitude = f"{abs(delta.delta):.0f}ms"
    else:
        magnitude = f"{abs(delta.delta):.1f}"
    if delta.direction == "stable":
        body = f"{delta.arrow}"
    else:
        body = f"{delta.arrow}{magnitude}"
    return f"<span class='metric-suffix'> {body}</span>"


# ---- Status banner (top of every tab) --------------------------------------


def _status_summary(model: DashboardModel) -> dict[str, list[str]]:
    """Aggregate the headline window's metric statuses into 3 buckets.

    Returns ``{"alert": [...], "warning": [...], "healthy": [...]}`` of
    metric labels, one per thresholded metric in ``METRIC_GETTERS``."""
    buckets: dict[str, list[str]] = {"alert": [], "warning": [], "healthy": []}
    for metric, getter in METRIC_GETTERS.items():
        if metric not in THRESHOLDS:
            continue
        value = getter(model)
        status = metric_status(metric, value)
        if status is None:
            continue
        buckets[status].append(METRIC_LABELS.get(metric, metric))
    return buckets


def format_status_banner(summary: dict[str, list[str]]) -> str:
    """Render the SENTINEL · N alerts · N warnings · N healthy banner.

    Alert names are listed beneath; warnings collapse by default; healthy is
    hidden behind a toggle. Hierarchy by severity per the design spec."""
    alerts = summary.get("alert", [])
    warnings = summary.get("warning", [])
    healthy = summary.get("healthy", [])

    counts = (
        f"<span class='count-alert'>{len(alerts)} alerts</span>"
        f"<span class='count-warning'>{len(warnings)} warnings</span>"
        f"<span class='count-healthy'>{len(healthy)} healthy</span>"
    )

    parts = [
        "<div class='status-banner'>",
        "<span class='status-title'>SENTINEL</span>",
        f"<span class='status-counts'>{counts}</span>",
    ]
    if alerts:
        parts.append(
            "<div class='status-list'>"
            "<span class='label'>Alerts:</span>"
            f"{', '.join(html.escape(name) for name in alerts)}"
            "</div>"
        )
    if warnings:
        parts.append(
            "<details>"
            f"<summary>{len(warnings)} warnings (expand)</summary>"
            f"<div class='status-list'>{', '.join(html.escape(n) for n in warnings)}</div>"
            "</details>"
        )
    if healthy:
        parts.append(
            "<details>"
            f"<summary>{len(healthy)} healthy (show)</summary>"
            f"<div class='status-list'>{', '.join(html.escape(n) for n in healthy)}</div>"
            "</details>"
        )
    parts.append("</div>")
    return "".join(parts)


# ---- Per-section / per-metric rendering (single header, 3 inline values) ---


# Each metric spec: (display_label, metric_name_or_None, getter, formatter)
# When metric_name is None the row is orientation only — no badge, no
# divergence highlight, no per-value colour.
def _all_attempts_rejected(record_attempts) -> bool:
    return any(not a.get("is_acceptable", True) for a in record_attempts)


METRIC_SPECS: list[tuple[str, list[tuple]]] = [
    ("Outcome", [
        ("Total interactions",         None,                          lambda m: m.total_interactions, str),
        ("Gap rate",                   "gap_rate",                    lambda m: m.gap_rate, _fmt_pct),
        ("Deflection rate",            "deflection_rate",             lambda m: m.deflection_rate, _fmt_pct),
        ("Refusal rate",               "refusal_rate",                lambda m: m.refusal_rate, _fmt_pct),
        ("Guardrail rejection rate",   "guardrail_rejection_rate",    lambda m: m.guardrail_rejection_rate, _fmt_pct),
        ("Retry-exhaustion rate",      "retry_exhausted_rate",        lambda m: m.retry_exhausted_rate, _fmt_pct),
    ]),
    ("Routing", [
        ("Branch distribution",        None,                          lambda m: m.branch_distribution, _fmt_branches),
        ("Low-confidence rate (<0.7)", "low_confidence_rate",         lambda m: m.low_confidence_rate(), _fmt_pct),
        ("Confident-failure rate (≥0.8 & failed)", "confident_failure_rate", lambda m: m.confident_failure_rate(), _fmt_pct),
        ("Multi-label rate",           None,                          lambda m: m.multi_label_rate, _fmt_pct),
    ]),
    ("Engagement", [
        ("Unique sessions",            None,                          lambda m: m.unique_sessions, str),
        ("Turns/session (median)",     "turns_per_session_median",    lambda m: m.turns_per_session_median, _fmt_num),
        ("Drop-off by turn",           None,                          lambda m: m.dropoff_by_turn, _fmt_dropoff),
        ("Contact-offer rate",         None,                          lambda m: m.contact_offer_rate, _fmt_pct),
        ("Contact-conversion rate",    "contact_conversion_rate",     lambda m: m.contact_conversion_rate, _fmt_pct),
    ]),
    ("Tool use", [
        ("Tool uptake (TECHNICAL)",    "technical_tool_uptake_rate",  lambda m: m.technical_tool_uptake_rate, _fmt_pct),
        ("Tool-call success rate",     None,                          lambda m: m.tool_call_success_rate, _fmt_pct),
    ]),
    ("Latency", [
        ("classifier",                 None,                          lambda m: m.latency_percentiles("classifier"), _fmt_latency_row),
        ("retrieval",                  None,                          lambda m: m.latency_percentiles("retrieval"), _fmt_latency_row),
        ("generation",                 None,                          lambda m: m.latency_percentiles("generation"), _fmt_latency_row),
        ("guardrail",                  None,                          lambda m: m.latency_percentiles("guardrail"), _fmt_latency_row),
        ("total (p95)",                "latency_p95_total",           lambda m: m.latency_percentiles("total").get(95), _fmt_ms),
    ]),
]


def _value_cell(
    metric_name: str | None,
    raw_value,
    formatted: str,
    *,
    divergent: bool,
    delta_html: str = "",
) -> str:
    classes = ["metric-value"]
    status = _status_class(metric_name, raw_value) if metric_name else ""
    if status:
        classes.append(status)
    if divergent:
        classes.append("divergent")
    return (
        f"<div class='{' '.join(classes)}'>"
        f"{html.escape(formatted)}{delta_html}"
        f"</div>"
    )


def _is_divergent(values: list[str]) -> bool:
    """A row diverges when its three formatted strings aren't all the same."""
    return len(set(values)) > 1


def _render_metric_row(
    label: str,
    metric_name: str | None,
    getter,
    formatter,
    models: list[DashboardModel],
    priors: list[DashboardModel | None],
) -> str:
    """One row in the metric grid: label + three windowed value cells + suffix."""
    raws = [getter(m) for m in models]
    formatted = [formatter(v) if formatter is not str else str(v) for v in raws]
    prior_raws = [getter(p) if p is not None else None for p in priors]
    divergent = _is_divergent(formatted)

    # When all three windows agree, render one value + "· same across windows"
    # in the suffix column; the other two value cells render empty so the grid
    # alignment stays.
    if not divergent:
        delta = _delta_inline(metric_name, raws[0], prior_raws[0])
        suffix = "<div class='metric-suffix'>· same across windows</div>"
        cells = [
            _value_cell(metric_name, raws[0], formatted[0], divergent=False, delta_html=delta),
            "<div></div>",
            "<div></div>",
            suffix,
        ]
    else:
        cells = []
        for i, (raw, fmt) in enumerate(zip(raws, formatted)):
            delta = _delta_inline(metric_name, raw, prior_raws[i])
            cells.append(_value_cell(
                metric_name, raw, fmt, divergent=True, delta_html=delta,
            ))
        cells.append("<div></div>")  # empty suffix when divergent
    return (
        f"<div class='metric-label'>{html.escape(label)}</div>"
        + "".join(cells)
    )


def format_metrics_overview(
    models: list[DashboardModel],
    priors: list[DashboardModel | None],
) -> str:
    """Full metrics overview: one section block per thematic group, each with
    a header row (window labels) + one metric row per spec."""
    blocks: list[str] = []
    for section_name, specs in METRIC_SPECS:
        rows: list[str] = []
        # Header row: first cell = section title placeholder; then 7d / 30d / Global.
        rows.append(
            "<div class='col-header'></div>"
            "<div class='col-header numeric'>7d</div>"
            "<div class='col-header numeric'>30d</div>"
            "<div class='col-header numeric'>Global</div>"
            "<div class='col-header'></div>"
        )
        for label, metric_name, getter, formatter in specs:
            rows.append(_render_metric_row(label, metric_name, getter, formatter, models, priors))
        blocks.append(
            f"<div class='section-block'>"
            f"<div class='section-title'>{section_name}</div>"
            f"<div class='metric-grid'>{''.join(rows)}</div>"
            f"</div>"
        )
    return "".join(blocks)


# ---- Failure Feed (inline expansion via accordions) ------------------------


def _truncate(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _failure_summary_html(row: FailureRow) -> str:
    """Render the accordion summary line — date / branch / mode / question / counts."""
    return (
        f"<div class='feed-meta mono'>{_fmt_date(row.timestamp)}</div>"
        f"<div class='feed-meta mono'>{html.escape(row.branch)}</div>"
        f"<div class='feed-mode {row.failure_mode}'>{row.failure_mode}</div>"
        f"<div class='feed-q'>{html.escape(_truncate(row.question))}</div>"
        f"<div class='feed-num mono'>{row.attempt_count}×</div>"
        f"<div class='feed-num mono'>{row.classification_confidence:.2f}</div>"
    )


def format_failure_drilldown(record: InteractionRecord) -> str:
    """Markdown drilldown for one failure — every per-attempt + chunk + tool-call field."""
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
    mode = classify_failure(record)
    badge = "PASS" if mode is None else f"FAIL · {mode}"
    truncated = record.question[:80] + ("…" if len(record.question) > 80 else "")
    return (
        f"<b>Turn {record.turn_index}</b> · {record.branch} · {record.event_type} · "
        f"{html.escape(truncated)} <i>[{badge}]</i>"
    )


def format_session_view(session: Session) -> str:
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
    if text is None:
        return DEFLECTION_EMPTY_PLACEHOLDER
    return text


# ---- Flags panel ------------------------------------------------------------


FLAGS_EMPTY_PLACEHOLDER = (
    "_No anomalies detected — every detector returned no flags. Stable / quiet "
    "weeks render no flags by design._"
)


def format_flags_summary(flags: list[Flag]) -> str:
    """HTML cards for each flag's headline + detail. The Investigate buttons
    are separate gr.Button instances built in build_app — this string is
    pure prose, no anchor links."""
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

# Healthy threshold stays GREEN (operator directive overrides the
# "muted gray for thresholds" recommendation from the design spec).
CHART_COLOR_MAP = {
    "actual":     "#a3a3a3",  # text-secondary — raw daily values, low saturation
    "3-day avg":  "#fafafa",  # text-primary — primary smoothed trend
    "healthy":    "#4ade80",  # healthy threshold reference
    "warning":    "#fbbf24",  # warning threshold reference
    "prior":      "#818cf8",  # divergence — prior-period overlay
}


def _y_axis_title(metric: str) -> str:
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
    if value is None:
        return None
    threshold = THRESHOLDS.get(metric)
    if threshold is not None and threshold.unit == "pp":
        return value * 100
    return value


def _fmt_metric_value(metric: str, value: float | None) -> str:
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
    """Long-format DataFrame for ``gr.LinePlot``: actual + 3-day-avg + thresholds."""
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


def _threshold_caption(metric: str) -> str:
    """Inline threshold caption text below each chart — replaces the legend."""
    t = THRESHOLDS.get(metric)
    if t is None:
        return ""
    if t.unit == "pp":
        h = f"{t.healthy * 100:.1f}%"
        w = f"{t.warning * 100:.1f}%"
    elif t.unit == "ms":
        h = f"{t.healthy:.0f} ms"
        w = f"{t.warning:.0f} ms"
    else:
        h = f"{t.healthy:.1f}"
        w = f"{t.warning:.1f}"
    direction = "≥" if t.higher_is_better else "≤"
    return f"healthy {direction} {h}  ·  warning {direction} {w}"


def format_trend_header(
    metric: str,
    model: DashboardModel,
    prior_model: DashboardModel | None = None,
) -> str:
    label = METRIC_LABELS.get(metric, metric)
    value = METRIC_GETTERS[metric](model)
    value_str = _fmt_metric_value(metric, value)
    status = _status_class(metric, value)
    coloured = (
        f"<span class='metric-value mono {status}'>{value_str}</span>" if status
        else f"<span class='mono'>{value_str}</span>"
    )
    prior_value = METRIC_GETTERS[metric](prior_model) if prior_model is not None else None
    delta = _delta_inline(metric, value, prior_value)
    return f"**{label}:** {coloured}{delta}"


# ---- Auto-refresh of cached cluster + summary files -------------------------


def is_stale(path: Path, max_age_days: int = DEFAULT_FRESHNESS_DAYS) -> bool:
    """True when ``path`` is missing or older than ``max_age_days``."""
    path = Path(path)
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime < datetime.now(timezone.utc) - timedelta(days=max_age_days)


def _run_with_capture(label: str, fn) -> str | None:
    try:
        fn()
        return None
    except Exception as exc:
        return f"{label} batch failed: {type(exc).__name__}: {exc}"


def ensure_fresh_clusters(
    log_path: Path | None = None,
    out_path: Path = CLUSTERS_DEFAULT_PATH,
    archive_dir: Path | None = CLUSTERS_ARCHIVE_DIR,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
) -> str | None:
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
    real = [m for m in messages if m]
    if not real:
        return ""
    inner = "<br>".join(html.escape(m) for m in real)
    return f"<div class='refresh-banner'>{inner}</div>"


# ---- App boot helpers -------------------------------------------------------


def _load(reader: LogReader) -> tuple[DashboardModel, datetime]:
    return DashboardModel(reader.read()), datetime.now(timezone.utc)


def _all_window_models(model: DashboardModel) -> tuple[list[DashboardModel], list[DashboardModel | None]]:
    """Return ``(models, priors)`` aligned with ``WINDOWS``."""
    models = [model.for_window(days=days) for _, days in WINDOWS]
    priors = [model.for_prior_window(days=days) for _, days in WINDOWS]
    return models, priors


def _filter_records(reader: LogReader, window_label: str) -> list[InteractionRecord]:
    days = dict(WINDOWS).get(window_label)
    return DashboardModel(reader.read()).for_window(days=days).records


# ---- build_app --------------------------------------------------------------


def build_app(reader: LogReader | None = None, *, autorefresh: bool = True) -> gr.Blocks:
    reader = reader or _default_reader()
    source = _source_label(reader)

    refresh_messages: list[str | None] = []
    if autorefresh:
        refresh_messages = [ensure_fresh_clusters(), ensure_fresh_summaries()]

    model, loaded_at = _load(reader)
    models, priors = _all_window_models(model)
    headline_model = model.for_window(days=HEADLINE_WINDOW_DAYS)
    initial_failures = select_failures(model.records)

    with gr.Blocks(title="Digital Twin · Sentinel", css=SENTINEL_CSS) as app:
        with gr.Row():
            gr.Markdown("# Digital Twin · Sentinel")
            refresh_btn = gr.Button("Refresh", variant="secondary", size="sm", scale=0)
        header_md = gr.Markdown(format_header(source, loaded_at))
        banner_md = gr.Markdown(_autorefresh_banner(refresh_messages))
        status_md = gr.Markdown(format_status_banner(_status_summary(headline_model)))

        with gr.Tabs() as tabs:
            # ---- Metrics tab ----------------------------------------------
            with gr.Tab("Metrics", id=TAB_METRICS):
                gr.Markdown("## Flags")
                flags_md = gr.Markdown(format_flags_summary(_build_flags(model)))

                # Per-flag Investigate buttons — one row of slot buttons, each
                # toggled visible/hidden + relabelled when the flag set changes.
                flag_buttons: list[gr.Button] = []
                with gr.Row():
                    for _ in range(MAX_FLAGS_RENDERED):
                        btn = gr.Button("", visible=False, size="sm", variant="secondary")
                        flag_buttons.append(btn)

                gr.Markdown("## Health overview")
                metrics_md = gr.Markdown(format_metrics_overview(models, priors))

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
                                with gr.Column(min_width=260):
                                    scan_headers[metric] = gr.Markdown(
                                        format_trend_header(metric, model)
                                    )
                                    scan_charts[metric] = gr.LinePlot(
                                        value=chart_dataframe(model, metric, days=30),
                                        x="date", y="value", color="series",
                                        x_title="Date",
                                        y_title=_y_axis_title(metric),
                                        color_map=CHART_COLOR_MAP,
                                        height=200, show_label=False,
                                        caption=_threshold_caption(metric),
                                    )
                                    scan_buttons[metric] = gr.Button(
                                        f"Investigate {METRIC_LABELS[metric]}",
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
                        height=520, show_label=False,
                    )
                    back_to_scan_btn = gr.Button("Back to scan", variant="secondary")

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

                feed_empty_md = gr.Markdown(
                    "" if initial_failures
                    else "<div class='feed-empty'>No failures match the current filters.</div>"
                )

                # Pre-allocated accordion slots. Each slot's `label` is set to
                # the row's summary line; body holds the full drilldown +
                # View Session button. Slots beyond the row count are hidden.
                feed_accordions: list[gr.Accordion] = []
                feed_drilldowns: list[gr.Markdown] = []
                feed_session_btns: list[gr.Button] = []
                feed_session_states: list[gr.State] = []
                for i in range(MAX_FEED_ROWS):
                    if i < len(initial_failures):
                        row = initial_failures[i]
                        label = (
                            f"{_fmt_date(row.timestamp)} · {row.branch} · "
                            f"{row.failure_mode} · {_truncate(row.question, 70)}"
                        )
                        body_md = format_failure_drilldown(row.record)
                        sid = row.record.session_id
                        visible = True
                    else:
                        label = ""
                        body_md = ""
                        sid = None
                        visible = False
                    with gr.Accordion(label=label, open=False, visible=visible) as acc:
                        feed_drilldowns.append(gr.Markdown(body_md))
                        feed_session_btns.append(
                            gr.Button("View full session", size="sm", variant="secondary")
                        )
                    feed_accordions.append(acc)
                    feed_session_states.append(gr.State(sid))

                with gr.Column(visible=False) as session_view:
                    session_md = gr.Markdown("")
                    back_btn = gr.Button("Back to feed", variant="secondary")

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
            updates = []
            for i in range(MAX_FLAGS_RENDERED):
                if i < len(flags):
                    f = flags[i]
                    updates.append(gr.update(
                        visible=True,
                        value=f"Investigate · {f.kind}",
                    ))
                else:
                    updates.append(gr.update(visible=False, value=""))
            return updates

        initial_flag_targets: list[str] = [
            FLAG_TARGET_TAB.get(f.target, TAB_METRICS) for f in _build_flags(model)
        ]
        initial_flag_targets += [""] * (MAX_FLAGS_RENDERED - len(initial_flag_targets))
        flag_targets_state = gr.State(initial_flag_targets)
        for i in range(min(len(_build_flags(model)), MAX_FLAGS_RENDERED)):
            flag_buttons[i].visible = True
            flag_buttons[i].value = f"Investigate · {_build_flags(model)[i].kind}"

        def _feed_accordion_updates(rows: list[FailureRow]):
            """Build (accordion-update, drilldown-update, session-state-value) per slot."""
            acc_updates, body_updates, state_values = [], [], []
            for i in range(MAX_FEED_ROWS):
                if i < len(rows):
                    row = rows[i]
                    label = (
                        f"{_fmt_date(row.timestamp)} · {row.branch} · "
                        f"{row.failure_mode} · {_truncate(row.question, 70)}"
                    )
                    acc_updates.append(gr.update(visible=True, label=label, open=False))
                    body_updates.append(format_failure_drilldown(row.record))
                    state_values.append(row.record.session_id)
                else:
                    acc_updates.append(gr.update(visible=False, label="", open=False))
                    body_updates.append("")
                    state_values.append(None)
            return acc_updates, body_updates, state_values

        # Refresh: reload disk + re-render every panel + auto-refresh batches
        def _refresh(branch, mode, window_label, search):
            cluster_msg = ensure_fresh_clusters() if autorefresh else None
            summary_msg = ensure_fresh_summaries() if autorefresh else None
            new_model, new_loaded_at = _load(reader)
            new_models, new_priors = _all_window_models(new_model)
            headline = new_model.for_window(days=HEADLINE_WINDOW_DAYS)

            records = new_model.for_window(days=dict(WINDOWS).get(window_label)).records
            failure_rows = select_failures(
                records, branch=branch, failure_mode=mode, question_search=search
            )
            flags = _build_flags(new_model)
            flag_targets = [FLAG_TARGET_TAB.get(f.target, TAB_METRICS) for f in flags]
            flag_targets += [""] * (MAX_FLAGS_RENDERED - len(flag_targets))
            acc_updates, body_updates, state_values = _feed_accordion_updates(failure_rows)
            empty_html = (
                "" if failure_rows
                else "<div class='feed-empty'>No failures match the current filters.</div>"
            )
            return [
                format_header(source, new_loaded_at),
                _autorefresh_banner([cluster_msg, summary_msg]),
                format_status_banner(_status_summary(headline)),
                format_flags_summary(flags),
                *_flag_button_updates(flags),
                flag_targets,
                format_metrics_overview(new_models, new_priors),
                empty_html,
                *acc_updates,
                *body_updates,
                *state_values,
                format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH)),
                format_deflection_panel(read_summary("deflection", DEFAULT_SUMMARIES_DIR)),
            ]

        refresh_btn.click(
            fn=_refresh,
            inputs=[branch_dd, mode_dd, window_dd, search_in],
            outputs=[
                header_md, banner_md, status_md,
                flags_md,
                *flag_buttons,
                flag_targets_state,
                metrics_md,
                feed_empty_md,
                *feed_accordions,
                *feed_drilldowns,
                *feed_session_states,
                cluster_md, deflection_md,
            ],
        )

        # Flag-click handlers: switch to the target tab
        def _make_flag_click(slot_index: int):
            def _handler(targets):
                target = targets[slot_index] if slot_index < len(targets) else ""
                if not target:
                    return gr.update()
                return gr.Tabs(selected=target)
            return _handler

        for i, btn in enumerate(flag_buttons):
            btn.click(
                fn=_make_flag_click(i),
                inputs=[flag_targets_state],
                outputs=[tabs],
            )

        # Failure feed filter changes → re-populate accordions
        def _refresh_feed(branch, mode, window_label, search):
            records = _filter_records(reader, window_label)
            rows = select_failures(
                records, branch=branch, failure_mode=mode, question_search=search
            )
            acc_updates, body_updates, state_values = _feed_accordion_updates(rows)
            empty_html = (
                "" if rows
                else "<div class='feed-empty'>No failures match the current filters.</div>"
            )
            return [
                empty_html,
                *acc_updates,
                *body_updates,
                *state_values,
            ]

        for control in (branch_dd, mode_dd, window_dd, search_in):
            control.change(
                fn=_refresh_feed,
                inputs=[branch_dd, mode_dd, window_dd, search_in],
                outputs=[
                    feed_empty_md,
                    *feed_accordions,
                    *feed_drilldowns,
                    *feed_session_states,
                ],
            )

        # View full session (per-row buttons) — swap to session-view column
        def _make_session_click(slot_index: int):
            def _handler(session_id):
                if not session_id:
                    return gr.update(), gr.update(), gr.update()
                sessions = group_by_session(reader.read())
                match = next((s for s in sessions if s.session_id == session_id), None)
                if match is None:
                    return gr.update(), gr.update(), gr.update()
                return (
                    gr.update(visible=False),  # collapse all accordions implicitly via column toggle
                    gr.update(visible=True),
                    format_session_view(match),
                )
            return _handler

        # We need a single "feed area" column to hide on session view; wrap
        # the feed_empty + accordions section in one column we can toggle.
        # That column wasn't built explicitly above — to keep this minimal,
        # toggle each accordion's visibility off when entering session view.
        # Simpler alternative: keep feed visible, render session_md inline
        # below it. Going with: per-button click hides session_view's parent
        # column toggle only.

        for i, btn in enumerate(feed_session_btns):
            btn.click(
                fn=_make_session_click(i),
                inputs=[feed_session_states[i]],
                outputs=[banner_md, session_view, session_md],  # banner_md is a no-op slot here
            )
            # NB: hiding the feed accordions wholesale would require wrapping
            # them in a column; keeping it simple — the session view appears
            # below the feed and the operator scrolls.

        def _back_to_feed():
            return gr.update(visible=False)

        back_btn.click(fn=_back_to_feed, outputs=[session_view])

        # Trend Explorer: investigate-mode renderer
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
                    gr.update(
                        value=df,
                        y_title=_y_axis_title(metric),
                        caption=_threshold_caption(metric),
                    ),
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
            caption = _threshold_caption(metric) if metric else ""
            return title, gr.update(value=df, y_title=y_title, caption=caption)

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

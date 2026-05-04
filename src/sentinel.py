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
import matplotlib

matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.dates as mdates
from matplotlib.figure import Figure
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
from contact_log import read_provided_session_ids
from dashboard_model import METRIC_GETTERS, DashboardModel
from flag_detector import (
    Flag,
    detect_gap_rate_jump,
    detect_new_cluster,
    detect_repeat_failure,
)
from summarize_failures import DEFAULT_SUMMARIES_DIR, latest_summary_path, read_summary
from failure_feed import (
    FAILURE_MODE_LABELS,
    FAILURE_MODE_SEVERITY,
    FAILURE_MODES,
    FailureRow,
    Session,
    classify_failure,
    failure_mode_counts,
    group_by_session,
    select_failures,
)
from interaction_log import InteractionRecord
from log_reader import HFReader, LocalReader, LogReader
from metric_status import THRESHOLDS, WoWDelta, metric_status, wow_delta


# Leftmost column = most recent. Operator opens Sentinel to check "what happened
# this week" first; broad context (Global) sits to the right as reference.
# 90d sits between 30d and Global so the column scan reads short → long.
WINDOWS = [("7d", 7), ("30d", 30), ("90d", 90), ("Global", None)]
HEADLINE_WINDOW_DAYS = 7  # Drives the status-banner counters

# Branch dropdown choices in Failure Feed.
BRANCH_CHOICES = ["All", *BRANCH_REGISTRY.keys()]
FAILURE_MODE_CHOICES = ["All", *FAILURE_MODES]

# Auto-refresh cadence — matches the documented weekly batch cadence so any
# launch sees data at most one cadence stale.
DEFAULT_FRESHNESS_DAYS = 7

# Smoothing window for the trend chart's rolling-average line.
ROLLING_AVG_DAYS = 3

# Minimum data span before WoW deltas carry semantic colour. With <14 days of
# log history a 'prior week' baseline is just a slice of the same chunk of
# data — colouring it green/red implies a real comparison that doesn't exist.
MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA = 14

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

# Window-display modes the metrics overview supports. Sentinel ships in
# ``stacked`` mode by default per operator directive — every row always shows
# the three windowed values so the columns scan consistently. The other modes
# remain available to direct callers but the UI doesn't expose a toggle.
DISPLAY_MODES: list[str] = ["stacked", "collapse-when-same", "inline"]
DISPLAY_MODE_DEFAULT = "stacked"

# Flag-button slot cap. Three detector kinds; up to 6 covers repeat_failure
# firing on multiple distinct questions.
MAX_FLAGS_RENDERED = 6


# ---- Midnight Mono CSS ------------------------------------------------------


SENTINEL_CSS = """
:root {
    --bg-base:       #0b0b0d;
    --bg-surface:    #141417;
    --bg-surface-2:  #1c1c20;   /* elevated cards (Flags / Charts) */
    --text-primary:  #f5f5f7;
    --text-secondary:#9999a3;
    --text-muted:    #5a5a64;
    --border:        #1f1f24;
    --border-strong: #2a2a30;
    --healthy:       #34d399;
    --warning:       #fbbf24;
    --alert:         #f87171;
    --divergence:    #a78bfa;
    --alert-tint:    rgba(248, 113, 113, 0.08);
    --warning-tint:  rgba(251, 191, 36, 0.06);
}

body, .gradio-container {
    background: var(--bg-base) !important;
    color: var(--text-primary);
    font-family: "Inter", ui-sans-serif, system-ui, -apple-system, sans-serif;
    font-weight: 400;
}

/* Tighter focus ring — subtle outline rather than the bright Gradio default. */
*:focus-visible {
    outline: 1px solid var(--text-secondary) !important;
    outline-offset: 1px !important;
    box-shadow: none !important;
}

/* Page padding — 32px outer rhythm for the dashboard shell. */
.gradio-container > .main { padding: 32px !important; }

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
    padding: 14px 18px;
    margin: 6px 0 14px;
}
.status-banner .status-header {
    display: flex; align-items: baseline; gap: 18px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}
.status-banner .status-title {
    font-weight: 600;
    letter-spacing: 0.08em;
    font-size: 0.85em;
    text-transform: uppercase;
    color: var(--text-secondary);
}
.status-counts span {
    font-weight: 600; font-size: 1em;
    margin-right: 16px;
}
.status-counts .count-alert    { color: var(--alert); }
.status-counts .count-warning  { color: var(--warning); }
.status-counts .count-healthy  { color: var(--healthy); }

.status-group {
    margin-top: 10px;
    padding: 6px 0 6px 12px;
    border-left: 3px solid transparent;
    display: flex; align-items: baseline; gap: 12px;
    flex-wrap: wrap;
}
.status-group.alert    { border-left-color: var(--alert); }
.status-group.warning  { border-left-color: var(--warning); }
.status-group.healthy  { border-left-color: var(--healthy); }
.status-group .group-label {
    font-weight: 700;
    font-size: 1em;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    min-width: 90px;
}
.status-group.alert    .group-label { color: var(--alert); }
.status-group.warning  .group-label { color: var(--warning); }
.status-group.healthy  .group-label { color: var(--healthy); }
.status-group .group-items {
    color: var(--text-primary);
    font-size: 0.95em;
}
.status-group.alert    .group-items { color: var(--text-primary); }
.status-group.warning  .group-items { color: var(--text-secondary); }
.status-group.healthy  .group-items { color: var(--text-secondary); }

/* ---- Section block (Metrics) ---- */
.section-block {
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-surface);
    padding: 10px 14px;
    margin: 8px 0;
}
.section-title {
    font-size: 1.05em; font-weight: 700;
    letter-spacing: 0.04em;
    color: var(--text-primary);
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px; margin-bottom: 10px;
}
.metric-row {
    display: grid;
    /* label + N windowed values — N = len(WINDOWS) (currently 4: 7d/30d/90d/Global). */
    grid-template-columns: 1.6fr repeat(4, 1fr);
    column-gap: 14px;
    align-items: baseline;
    padding: 4px 8px;
    border-radius: 3px;
    border-left: 3px solid transparent;
    margin: 1px 0;
}
.metric-row .col-header,
.metric-row.header > div {
    font-size: 0.72em; font-weight: 500;
    color: var(--text-muted);
    letter-spacing: 0.08em; text-transform: uppercase;
    padding-bottom: 2px;
    border-bottom: 1px solid var(--border);
}
.metric-row.header .col-header.numeric { text-align: right; }
.metric-row .metric-label { color: var(--text-primary); }
.metric-row .metric-value {
    text-align: right;
    color: var(--text-primary);
    padding: 1px 6px;
    border-radius: 2px;
}
.metric-row .metric-value.healthy { color: var(--healthy); }
.metric-row .metric-value.warning { color: var(--warning); }
.metric-row .metric-value.alert   { color: var(--alert); }
.metric-row .metric-value.divergent {
    border: 1px solid var(--divergence);
}
.metric-row .metric-suffix {
    color: var(--text-muted);
    font-size: 0.85em;
}
/* WoW delta colouring — muted until 14d of history exists, semantic after. */
.delta {
    font-size: 11px;
    margin-left: 4px;
    color: var(--text-muted);
}
.delta.improving { color: var(--healthy); }
.delta.degrading { color: var(--alert); }
.delta.stable    { color: var(--text-muted); }
.delta.muted     { color: var(--text-muted); }
.metric-row .metric-value-inline {
    /* Inline mode: the joined "9.4% / 9.4% / 9.4% / 9.4%" cell spans all
       windowed value columns. */
    grid-column: 2 / -1;
    text-align: right;
    color: var(--text-primary);
    padding: 1px 6px;
}
.metric-row .metric-value-inline .inline-value {
    color: var(--text-primary);
    margin: 0 2px;
}
.metric-row .metric-value-inline .inline-value.healthy { color: var(--healthy); }
.metric-row .metric-value-inline .inline-value.warning { color: var(--warning); }
.metric-row .metric-value-inline .inline-value.alert   { color: var(--alert); }
.metric-row .metric-value-inline .inline-value.divergent {
    border: 1px solid var(--divergence);
    border-radius: 2px;
    padding: 0 4px;
}
.metric-row .metric-value-inline .inline-sep {
    color: var(--text-muted);
    margin: 0 2px;
}

/* Severity-driven row treatment — alerts dominate visually, healthy collapses
   in density but keeps a green ribbon so the column scans symmetrically. Font
   sizes stay consistent across severities (operator directive — no value-size
   bump). The left ribbon does the work of differentiating severity. */
.metric-row.row-alert {
    background: rgba(248, 113, 113, 0.06);
    border-left-color: var(--alert);
    padding-top: 8px; padding-bottom: 8px;
    margin: 4px 0;
}
.metric-row.row-alert .metric-label {
    font-weight: 500;
}
.metric-row.row-warning {
    border-left-color: var(--warning);
    border-left-width: 2px;
}
.metric-row.row-orientation {
    /* No left border, standard density. Context rows stay legible without
       claiming visual urgency. */
}
.metric-row.row-healthy {
    border-left-color: var(--healthy);
    border-left-width: 2px;
    padding-top: 1px; padding-bottom: 1px;
}
.metric-row.row-healthy .metric-label {
    color: var(--text-secondary);
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
.feed-summary {
    padding: 8px 0 16px;
    color: var(--text-secondary);
    font-size: 0.92em;
}
.feed-summary .feed-summary-total {
    font-weight: 600;
    color: var(--text-primary);
    margin-right: 8px;
}
.feed-summary .feed-summary-mode {
    margin-right: 12px;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
/* Per-mode colour palette — distinct per failure mode, all visible against
   the dark background. refused = bright red; retry-exhausted = orange (needed
   recovery loop but failed); rejected-then-recovered = amber (recovered);
   gap = info-blue (operator-friendly, distinct from the gray that disappears
   into the background). */
.feed-summary .feed-summary-mode.refused                  { color: #f87171; }
.feed-summary .feed-summary-mode.retry-exhausted          { color: #fb923c; }
.feed-summary .feed-summary-mode.rejected-then-recovered  { color: #fbbf24; }
.feed-summary .feed-summary-mode.gap                      { color: #60a5fa; }

.feed-row {
    border: 1px solid var(--border);
    border-left: 3px solid transparent;
    border-radius: 3px;
    background: var(--bg-surface);
    margin: 4px 0;
}
.feed-row.sev-refused                  { border-left-color: #f87171; }
.feed-row.sev-retry-exhausted          { border-left-color: #fb923c; }
.feed-row.sev-rejected-then-recovered  { border-left-color: #fbbf24; }
.feed-row.sev-gap                      { border-left-color: #60a5fa; }

.feed-row summary {
    list-style: none; cursor: pointer;
    padding: 8px 12px;
    display: grid;
    grid-template-columns: 100px 100px 220px 1fr 60px 60px;
    column-gap: 14px; align-items: center;
}
.feed-row summary::-webkit-details-marker { display: none; }
.feed-row .feed-meta {
    color: var(--text-secondary);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.92em;
}
/* Branch + mode rendered as monospace pills */
.feed-pill {
    display: inline-block;
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
}
.feed-pill.sev-alert    { color: var(--alert); border-color: var(--alert); }
.feed-pill.sev-warning  { color: var(--warning); border-color: var(--warning); }
.feed-pill.sev-muted    { color: var(--text-muted); border-color: var(--text-muted); }

.feed-row .feed-q { color: var(--text-primary); }
.feed-row .feed-num {
    color: var(--text-secondary); text-align: right;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.92em;
}
.feed-row[open] summary { border-bottom: 1px solid var(--border); }
.feed-row .feed-body { padding: 10px 14px; color: var(--text-primary); }

.feed-empty {
    padding: 18px; text-align: center;
    color: var(--text-muted); font-style: italic;
}

/* Session drilldown header — clearly delineates "you're now viewing one
   session" from the multi-row failure feed. */
.session-view-header {
    background: var(--bg-surface-2);
    border: 1px solid var(--border);
    border-left: 3px solid var(--divergence);
    border-radius: 6px;
    padding: 14px 18px;
    margin: 8px 0 16px;
}
.session-view-header .session-eyebrow {
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--divergence);
    margin-bottom: 4px;
}
.session-view-header .session-question {
    font-size: 16px;
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 6px;
}
.session-view-header .session-meta {
    font-size: 12px;
    color: var(--text-secondary);
}
.session-view-header .session-meta code {
    background: var(--bg-base);
    border: 1px solid var(--border);
    padding: 1px 6px;
    border-radius: 3px;
    margin-right: 4px;
    color: var(--text-muted);
}

/* ---- Gap clusters (2-column card grid) ---- */
.cluster-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 12px;
    margin-top: 8px;
}
.cluster-card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px 16px;
}
.cluster-card .cluster-header {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
}
.cluster-card .cluster-label {
    font-weight: 600;
    color: var(--text-primary);
}
.cluster-card .cluster-count {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.82em;
    color: var(--text-muted);
    background: var(--bg-base);
    padding: 1px 8px;
    border-radius: 4px;
}
.cluster-card ul {
    margin: 0; padding-left: 1.1em;
    color: var(--text-secondary);
    font-size: 0.92em;
}
.cluster-card li { margin: 3px 0; }
.cluster-card .cluster-meta {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.78em;
    color: var(--text-muted);
}

/* ---- Charts: caption styling ---- */
.threshold-caption {
    color: var(--text-muted);
    font-size: 0.82em;
    margin-top: 2px;
}

/* Restraint: no shadows, no gradients, small radii everywhere */
button { border-radius: 6px !important; }

/* Hide Gradio default footer ("Built with Gradio · Settings · Use via API") */
footer { display: none !important; }

/* ---- Page header (eyebrow + title + metadata line) ---- */
.page-header {
    display: flex; align-items: flex-end; justify-content: space-between;
    margin-bottom: 16px;
}
.page-header .eyebrow {
    font-size: 11px; font-weight: 400;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--text-secondary);
    margin-bottom: 4px;
}
.page-header .page-title {
    font-size: 28px; font-weight: 500;
    color: var(--text-primary);
    line-height: 1.1;
}
.page-header .page-meta {
    margin-top: 8px;
    font-family: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;
    font-size: 12px;
    color: var(--text-muted);
}

/* Ghost Refresh button — transparent, 1px subtle border, 32px height. */
.ghost-button button {
    background: transparent !important;
    border: 1px solid var(--border-strong) !important;
    color: var(--text-secondary) !important;
    height: 32px !important;
    border-radius: 6px !important;
    font-weight: 400 !important;
}
.ghost-button button:hover {
    color: var(--text-primary) !important;
    border-color: var(--text-secondary) !important;
}

/* ---- Section header (between sections; no card wrappers) ---- */
.section-header {
    font-size: 15px; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--text-primary);
    margin: 32px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
}
.section-header:first-of-type { margin-top: 12px; }

/* Latency stages — p50 muted, p95 primary, drives the eye to the headline. */
.metric-row .latency-p50 { color: var(--text-secondary); }
.metric-row .latency-p95 { color: var(--text-primary); font-weight: 500; }

/* ---- Chart card — wrap each scan-mode chart in a bordered surface ---- */
.chart-card {
    background: var(--bg-surface-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 12px 8px;
    margin: 4px 0;
}
.chart-card .chart-header {
    margin-bottom: 4px;
    color: var(--text-primary);
}
.chart-card .gradio-plot, .chart-card img, .chart-card svg {
    width: 100% !important; max-width: 100%;
}

/* Investigate link — no chrome; small, muted, hover lifts to primary. */
.investigate-link button {
    background: transparent !important;
    border: none !important;
    color: var(--text-muted) !important;
    font-size: 11px !important;
    padding: 2px 0 !important;
    height: auto !important;
    text-align: left !important;
    text-transform: lowercase;
    letter-spacing: 0.02em;
}
.investigate-link button:hover {
    color: var(--text-primary) !important;
}

/* ---- Filter bar (Failures) — single 36px row ---- */
.filter-bar { gap: 8px !important; }
.filter-bar .gradio-dropdown,
.filter-bar .gradio-textbox { min-height: 36px !important; }
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
    """Date-only render (``YYYY-MM-DD``) for any ISO timestamp / datetime /
    date / pd.Timestamp."""
    if value is None:
        return EM_DASH
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date().isoformat()
        return value.astimezone(timezone.utc).date().isoformat()
    return str(value)[:10]


def format_header(source: str, loaded_at: datetime) -> str:
    """Single-line metadata for the page header — source + load date in mono."""
    return f"{source}  ·  loaded {_fmt_date(loaded_at)}"


def _fmt_pct(rate: float | None) -> str:
    return EM_DASH if rate is None else f"{rate * 100:.1f}%"


def _fmt_seconds(ms: float | None) -> str:
    """Render latency in seconds with 2 decimals (operator directive — ms is
    too granular to scan; sub-second precision isn't load-bearing)."""
    return EM_DASH if ms is None else f"{ms / 1000:.2f} s"


# Backwards-compatible alias for older call sites — same seconds rendering.
_fmt_ms = _fmt_seconds


def _fmt_num(n: float | None, ndigits: int = 1) -> str:
    return EM_DASH if n is None else f"{n:.{ndigits}f}"


def _fmt_branches(distribution: dict[str, float]) -> str:
    if not distribution:
        return EM_DASH
    parts = sorted(distribution.items(), key=lambda kv: -kv[1])
    return " | ".join(f"{branch} {fraction * 100:.0f}%" for branch, fraction in parts)


def _fmt_dropoff(dropoff: dict[int, int]) -> str:
    """Surface only the most common drop-off turn — the operator wants the
    headline pattern (where do most users last interact?), not the per-turn
    table. Computed as ``count_at_N − count_at_N+1`` for each N; biggest
    drop wins."""
    if not dropoff:
        return EM_DASH
    sorted_counts = sorted(dropoff.items())
    drops: dict[int, int] = {}
    for i, (turn, count) in enumerate(sorted_counts):
        next_count = sorted_counts[i + 1][1] if i + 1 < len(sorted_counts) else 0
        drops[turn] = count - next_count
    most_common = max(drops, key=drops.get)
    return f"after t{most_common} ({drops[most_common]} sessions)"


def _fmt_latency_row(p: dict[int, float | None]) -> str:
    """Two-tier latency display — p50 in muted secondary, p95 in primary so
    the operator's eye lands on the headline tail value."""
    p50 = _fmt_seconds(p.get(50))
    p95 = _fmt_seconds(p.get(95))
    return (
        f"<span class='latency-p50'>p50 {p50}</span>"
        f" / "
        f"<span class='latency-p95'>p95 {p95}</span>"
    )


# ---- Threshold-aware rendering helpers --------------------------------------


def _status_class(metric_name: str | None, value: float | None) -> str:
    """CSS class for the metric value cell — drives the colour treatment."""
    if metric_name is None:
        return ""
    return metric_status(metric_name, value) or ""


def _data_history_days(records: list[InteractionRecord]) -> int:
    """Number of days spanned by the record set (max-timestamp − min-timestamp).

    Drives the delta-colour gate: with <14d the WoW comparison isn't a real
    'this week vs last week' read, so deltas render muted to suppress false
    alarms before the system has accumulated enough history to be trusted."""
    if not records:
        return 0
    timestamps = [r.timestamp for r in records]
    earliest = min(timestamps)[:10]
    latest = max(timestamps)[:10]
    try:
        d_early = datetime.fromisoformat(earliest).date()
        d_late = datetime.fromisoformat(latest).date()
    except ValueError:
        return 0
    return (d_late - d_early).days


def _delta_inline(
    metric_name: str | None,
    current,
    prior,
    history_days: int = 0,
) -> str:
    """Compact inline delta arrow (post-value), or empty string when no delta applies.

    When ``history_days < MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA`` the delta
    renders in muted colour at 11px — there isn't enough history yet for the
    'good vs bad' interpretation to be trustworthy. Above that threshold the
    delta picks up the semantic colour (improving = healthy green; degrading
    = alert red; stable = muted) — direction already accounts for the
    metric's polarity (gap rate up = degrading; tool-call success up =
    improving) via ``wow_delta``.
    """
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
    css_class = (
        "delta muted" if history_days < MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA
        else f"delta {delta.direction}"
    )
    return f"<span class='{css_class}'>{body}</span>"


# ---- Status banner (top of every tab) --------------------------------------


# Plain-language labels for the status banner — strip parentheticals and
# operator jargon so the banner reads to anyone, not just the engineer who
# wrote the metric definitions. Metric grids elsewhere keep the technical
# names; this map is banner-only.
FRIENDLY_BANNER_LABELS: dict[str, str] = {
    "gap_rate":                     "Unknown answers",
    "deflection_rate":              "Deflected to story",
    "refusal_rate":                 "Refused to answer",
    "guardrail_rejection_rate":     "Quality-check rejections",
    "retry_exhausted_rate":         "Retries exhausted",
    "low_confidence_rate":          "Uncertain classifications",
    "confident_failure_rate":       "Misclassified questions",
    "latency_p95_total":            "Slow responses",
    "technical_tool_uptake_rate":   "Tool usage",
    "contact_conversion_rate":      "Contact form submitted",
    "turns_per_session_median":     "Conversation depth",
}


def _status_summary(model: DashboardModel) -> dict[str, list[str]]:
    """Aggregate the headline window's metric statuses into 3 buckets.

    Returns ``{"alert": [...], "warning": [...], "healthy": [...]}`` of
    *friendly* metric labels (banner-readable, not technical)."""
    buckets: dict[str, list[str]] = {"alert": [], "warning": [], "healthy": []}
    for metric, getter in METRIC_GETTERS.items():
        if metric not in THRESHOLDS:
            continue
        value = getter(model)
        status = metric_status(metric, value)
        if status is None:
            continue
        buckets[status].append(FRIENDLY_BANNER_LABELS.get(metric, METRIC_LABELS.get(metric, metric)))
    return buckets


def format_status_banner(summary: dict[str, list[str]]) -> str:
    """Render the SENTINEL banner — counts header + always-expanded groups.

    Banner is intentionally short (one row per severity, items separated by
    ``|``); no collapse-toggles because the per-group lists are already
    short enough to scan inline."""
    alerts = summary.get("alert", [])
    warnings = summary.get("warning", [])
    healthy = summary.get("healthy", [])

    counts = (
        f"<span class='count-alert'>{len(alerts)} alerts</span>"
        f"<span class='count-warning'>{len(warnings)} warnings</span>"
        f"<span class='count-healthy'>{len(healthy)} healthy</span>"
    )

    def _group(severity: str, names: list[str]) -> str:
        if not names:
            return (
                f"<div class='status-group {severity}'>"
                f"<span class='group-label'>{severity.title()}</span>"
                f"<span class='group-items'>—</span>"
                f"</div>"
            )
        items = " | ".join(html.escape(n) for n in names)
        return (
            f"<div class='status-group {severity}'>"
            f"<span class='group-label'>{severity.title()}</span>"
            f"<span class='group-items'>{items}</span>"
            f"</div>"
        )

    # Drop the explicit "SENTINEL" prefix — the page header already names
    # the dashboard, and the per-severity counts speak for themselves.
    return (
        "<div class='status-banner'>"
        "<div class='status-header'>"
        f"<span class='status-counts'>{counts}</span>"
        "</div>"
        f"{_group('alert', alerts)}"
        f"{_group('warning', warnings)}"
        f"{_group('healthy', healthy)}"
        "</div>"
    )


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
        ("Classifier branch distribution",         None,                          lambda m: m.branch_distribution, _fmt_branches),
        ("Classifier mean confidence",             None,                          lambda m: m.mean_classification_confidence, lambda v: _fmt_num(v, 2)),
        ("Classifier low-confidence rate (<0.7)",  "low_confidence_rate",         lambda m: m.low_confidence_rate(), _fmt_pct),
        ("Classifier confident-failure rate (≥0.8 & failed)", "confident_failure_rate", lambda m: m.confident_failure_rate(), _fmt_pct),
        ("Classifier multi-label rate",            None,                          lambda m: m.multi_label_rate, _fmt_pct),
    ]),
    ("Engagement", [
        ("Unique sessions",            None,                          lambda m: m.unique_sessions, str),
        ("Avg questions per session",  None,                          lambda m: m.mean_turns_per_session, lambda v: _fmt_num(v, 2)),
        ("Turns/session (median)",     "turns_per_session_median",    lambda m: m.turns_per_session_median, _fmt_num),
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
    """Wrap a formatted value in its severity-coloured cell.

    ``formatted`` is trusted as safe HTML — formatters in this module
    produce strings from controlled internal data (rates, latencies, branch
    distributions over the registry), no user input. Escaping here would
    break the embedded ``<span>`` markup the latency formatter uses to
    differentiate p50 / p95."""
    classes = ["metric-value"]
    status = _status_class(metric_name, raw_value) if metric_name else ""
    if status:
        classes.append(status)
    if divergent:
        classes.append("divergent")
    return (
        f"<div class='{' '.join(classes)}'>"
        f"{formatted}{delta_html}"
        f"</div>"
    )


def _is_divergent(values: list[str]) -> bool:
    """A row diverges when its three formatted strings aren't all the same."""
    return len(set(values)) > 1


def _row_severity(metric_name: str | None, raws: list) -> str:
    """Worst per-window status across the three windows — drives the row's
    visual treatment. Orientation metrics (no threshold) → 'orientation'.

    Worst-status ranking: alert > warning > healthy. A metric that's healthy
    on 7d but alerted on Global gets the alert row treatment so the operator
    can't miss it."""
    if metric_name is None:
        return "orientation"
    statuses = {metric_status(metric_name, v) for v in raws}
    if "alert" in statuses:
        return "alert"
    if "warning" in statuses:
        return "warning"
    if "healthy" in statuses:
        return "healthy"
    return "orientation"


# Sort priority within a section. Lower number → rendered higher.
_SEVERITY_RANK = {"alert": 0, "warning": 1, "orientation": 2, "healthy": 3}


def _inline_value_cell(
    metric_name: str | None,
    raws: list,
    formatted: list[str],
    divergent: bool,
) -> str:
    """Pack the three windowed values into one cell: ``9.4% / 9.4% / 9.4%``.

    Each value gets its own status colour; divergent values get the
    divergence accent inline. Used by the ``inline`` display mode."""
    parts: list[str] = []
    for i, (raw, fmt) in enumerate(zip(raws, formatted)):
        classes = ["inline-value"]
        status = _status_class(metric_name, raw) if metric_name else ""
        if status:
            classes.append(status)
        if divergent:
            classes.append("divergent")
        parts.append(
            f"<span class='{' '.join(classes)}'>{html.escape(fmt)}</span>"
        )
    joiner = "<span class='inline-sep'>/</span>"
    return f"<div class='metric-value-inline'>{joiner.join(parts)}</div>"


def _render_metric_row(
    label: str,
    metric_name: str | None,
    getter,
    formatter,
    models: list[DashboardModel],
    priors: list[DashboardModel | None],
    severity: str,
    display_mode: str = DISPLAY_MODE_DEFAULT,
    history_days: int = 0,
) -> str:
    """One row in the metric grid: label + windowed value cells + suffix.

    ``display_mode`` controls how the three windowed values lay out:

    - ``collapse-when-same`` (default): one cell + ``· same across windows``
      suffix when identical; three separate cells when divergent.
    - ``stacked``: three separate cells always.
    - ``inline``: one cell with ``9.4% / 9.4% / 9.4%`` style inline values.
    """
    raws = [getter(m) for m in models]
    formatted = [formatter(v) if formatter is not str else str(v) for v in raws]
    prior_raws = [getter(p) if p is not None else None for p in priors]
    divergent = _is_divergent(formatted)

    n_windows = len(models)
    if display_mode == "inline":
        # One spanning cell that joins all N values inline.
        cells = [_inline_value_cell(metric_name, raws, formatted, divergent)]
    elif display_mode == "stacked":
        cells = []
        for i, (raw, fmt) in enumerate(zip(raws, formatted)):
            delta = _delta_inline(metric_name, raw, prior_raws[i], history_days)
            cells.append(_value_cell(
                metric_name, raw, fmt, divergent=divergent, delta_html=delta,
            ))
    else:  # collapse-when-same
        if not divergent:
            # Render the value in column 1; tag the inline suffix onto its
            # delta_html so the "· same across windows" hint sits beside the
            # value rather than occupying its own column. The remaining
            # window columns render empty so the grid stays aligned.
            delta = _delta_inline(metric_name, raws[0], prior_raws[0], history_days)
            suffix = "<span class='metric-suffix'> · same across windows</span>"
            cells = [
                _value_cell(metric_name, raws[0], formatted[0], divergent=False,
                            delta_html=delta + suffix),
            ]
            for _ in range(n_windows - 1):
                cells.append("<div></div>")
        else:
            cells = []
            for i, (raw, fmt) in enumerate(zip(raws, formatted)):
                delta = _delta_inline(metric_name, raw, prior_raws[i], history_days)
                cells.append(_value_cell(
                    metric_name, raw, fmt, divergent=True, delta_html=delta,
                ))
    return (
        f"<div class='metric-row row-{severity}'>"
        f"<div class='metric-label'>{html.escape(label)}</div>"
        + "".join(cells)
        + "</div>"
    )


def format_metrics_overview(
    models: list[DashboardModel],
    priors: list[DashboardModel | None],
    display_mode: str = DISPLAY_MODE_DEFAULT,
) -> str:
    """Full metrics overview: one section block per thematic group.

    Within each section, rows are sorted by severity (alerts first, then
    warnings, then orientation context, then healthy). Each row carries a
    severity CSS class so the alert ones dominate visually and healthy ones
    collapse to a compact line. ``display_mode`` ∈ {collapse-when-same,
    stacked, inline} controls how the three windowed values lay out.

    History depth is computed from the Global window's record set and
    threaded through to ``_delta_inline`` so deltas render muted until the
    log spans at least ``MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA`` days."""
    # Global model is the third entry per WINDOWS = [(7d, 7), (30d, 30), (Global, None)].
    history_days = _data_history_days(models[-1].records) if models else 0

    blocks: list[str] = []
    for section_name, specs in METRIC_SPECS:
        annotated = []
        for spec in specs:
            label, metric_name, getter, formatter = spec
            raws = [getter(m) for m in models]
            severity = _row_severity(metric_name, raws)
            annotated.append((severity, spec))
        annotated.sort(key=lambda pair: _SEVERITY_RANK.get(pair[0], 99))

        # One header cell per window — derived from WINDOWS so adding a window
        # doesn't drift from the body cells below.
        window_headers = "".join(
            f"<div class='col-header numeric'>{label}</div>"
            for label, _ in WINDOWS
        )
        rows = [
            "<div class='metric-row header'>"
            "<div class='col-header'></div>"
            f"{window_headers}"
            "</div>"
        ]
        for severity, (label, metric_name, getter, formatter) in annotated:
            rows.append(_render_metric_row(
                label, metric_name, getter, formatter, models, priors,
                severity, display_mode, history_days,
            ))
        # No card wrapper — whitespace + the section header carry the
        # separation. Cleaner, less chrome (operator directive).
        blocks.append(
            f"<div class='section-header'>{section_name}</div>"
            f"{''.join(rows)}"
        )
    return "".join(blocks)


# ---- Failure Feed (inline expansion via accordions) ------------------------


def _truncate(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _failure_accordion_label(row: FailureRow) -> str:
    """Single-line accordion label — Gradio's Accordion only accepts plain text
    so the visual treatment lives on the row container; this is the headline."""
    return (
        f"{_fmt_date(row.timestamp)}  ·  {row.branch}  ·  "
        f"{FAILURE_MODE_LABELS.get(row.failure_mode, row.failure_mode)}  ·  "
        f"{_truncate(row.question, 90)}"
    )


def format_feed_summary(rows: list[FailureRow], counts: dict[str, int]) -> str:
    """Per-mode counts row above the feed.

    'Total · 8 unknown answer · 5 rejected then recovered · 1 retry exhausted
    · 1 refused' — the mode counts use the friendly labels so the operator
    sees the underlying-field mapping at a glance, and each count is colored
    by its severity for at-a-glance scan."""
    total = len(rows)
    if total == 0:
        return ""
    parts = [
        f"<span class='feed-summary-total'>{total} failures</span>"
    ]
    # Sort the count breakdown by mode rank so the most-actionable modes
    # (refused → retry-exhausted → rejected-then-recovered → gap) appear first.
    from failure_feed import _SEVERITY_RANK as _MODE_RANK  # per-mode sort order
    sorted_modes = sorted(counts.items(), key=lambda kv: _MODE_RANK.get(kv[0], 99))
    for mode, n in sorted_modes:
        if n == 0:
            continue
        friendly = FAILURE_MODE_LABELS.get(mode, mode).split(" (")[0]
        parts.append(
            f"<span class='feed-summary-mode {mode}'>{n} {html.escape(friendly)}</span>"
        )
    return "<div class='feed-summary'>" + "".join(parts) + "</div>"


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
    """Per-session view, prefixed with a prominent header so the operator
    sees clearly that they've left the feed and entered a single-session
    drilldown."""
    contact_bits = []
    if session.contact_offered:
        contact_bits.append("offered")
    if session.contact_provided:
        contact_bits.append("provided")
    contact_str = ", ".join(contact_bits) if contact_bits else "neither"

    first_q = (
        session.records[0].question if session.records else "(no records)"
    )
    first_q_truncated = first_q[:120] + ("…" if len(first_q) > 120 else "")

    header = (
        "<div class='session-view-header'>"
        "<div class='session-eyebrow'>Session drilldown</div>"
        f"<div class='session-question'>{html.escape(first_q_truncated)}</div>"
        f"<div class='session-meta mono'>"
        f"<code>{session.session_id}</code>  ·  "
        f"{session.turn_count} turns  ·  "
        f"contact: {contact_str}  ·  "
        f"total latency: {session.total_latency_ms / 1000:.2f} s"
        "</div>"
        "</div>"
    )

    parts = [header, ""]
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
    "<div class='cluster-card' style='text-align:center; "
    "color: var(--text-muted); font-style: italic;'>"
    "No cached deflection summary yet. Auto-refresh skipped — no deflection "
    "turns in window, or LLM unavailable."
    "</div>"
)


def format_cluster_panel(data: dict | None) -> str:
    """Render gap clusters as a responsive 2-column card grid (one card per
    cluster) — easier to scan than a flat bullet list when there are several
    clusters of varying sizes."""
    if data is None:
        return CLUSTER_EMPTY_PLACEHOLDER
    clusters = data.get("clusters", [])
    if not clusters:
        return (
            f"_No clusters in the last {data.get('period_days', '?')} days "
            "(no gap turns, or all groups below the minimum size)._"
        )
    cards: list[str] = []
    for cluster in clusters:
        examples = cluster.get("examples", [])
        examples_html = (
            "<ul>"
            + "".join(f"<li>{html.escape(ex)}</li>" for ex in examples)
            + "</ul>"
        ) if examples else ""
        cards.append(
            "<div class='cluster-card'>"
            "<div class='cluster-header'>"
            f"<span class='cluster-label'>{html.escape(cluster['label'])}</span>"
            f"<span class='cluster-count'>{cluster['count']}</span>"
            "</div>"
            f"{examples_html}"
            "</div>"
        )
    meta = (
        f"<div class='cluster-meta'>generated {_fmt_date(data.get('generated_at'))} "
        f"· window {data.get('period_days', '?')}d</div>"
    )
    return meta + "<div class='cluster-grid'>" + "".join(cards) + "</div>"


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

# Per-status palette: (dim shade for actual line, bright shade for trend).
# Replaces the static fixed-threshold reference lines with dynamic colouring
# of the value + trend series based on the metric's current status.
_STATUS_CHART_COLOR: dict[str | None, tuple[str, str]] = {
    "healthy": ("#166534", "#4ade80"),  # green-800, green-400
    "warning": ("#92400e", "#fbbf24"),  # amber-800, amber-400
    "alert":   ("#991b1b", "#f87171"),  # red-800,   red-400
    None:      ("#525252", "#a3a3a3"),  # text-muted / text-secondary (orientation)
}

# Prior-overlay colour stays constant (compares against current period's data,
# which already carries the status colouring on its own series).
_PRIOR_CHART_COLOR = "#818cf8"


def _y_axis_title(metric: str) -> str:
    label = METRIC_LABELS.get(metric, metric)
    threshold = THRESHOLDS.get(metric)
    if threshold is None:
        return label
    if threshold.unit == "pp":
        return f"{label} (%)"
    if threshold.unit == "ms":
        return f"{label} (s)"
    return label


def _scale_value(metric: str, value: float | None) -> float | None:
    """Convert raw values to chart-axis units. ``pp`` → percentages (×100);
    ``ms`` → seconds (÷1000); other passes through."""
    if value is None:
        return None
    threshold = THRESHOLDS.get(metric)
    if threshold is None:
        return value
    if threshold.unit == "pp":
        return value * 100
    if threshold.unit == "ms":
        return value / 1000
    return value


def _fmt_metric_value(metric: str, value: float | None) -> str:
    threshold = THRESHOLDS.get(metric)
    if threshold is None:
        return _fmt_num(value)
    if threshold.unit == "pp":
        return _fmt_pct(value)
    if threshold.unit == "ms":
        return _fmt_seconds(value)
    return _fmt_num(value)


def chart_dataframe(
    model: DashboardModel,
    metric: str,
    days: int | None,
    *,
    prior_model: DashboardModel | None = None,
) -> pd.DataFrame:
    """Long-format DataFrame for the trend chart: ``actual`` + ``3-day avg``
    (+ optional ``prior``).

    Trimmed to ``[first_real_data − 2d, last_real_data]`` so the chart's
    x-axis doesn't carry empty space when the log spans only a few days.
    No threshold reference rows — status colouring on the trend line itself
    carries the healthy/warning/alert signal (the threshold *values* live in
    the chart caption)."""
    series = model.time_series_by_day(metric, days=days)
    if not series:
        return pd.DataFrame(columns=["date", "value", "series"])

    raw = pd.DataFrame(series, columns=["date", "value"])
    raw["date"] = pd.to_datetime(raw["date"])
    raw["value"] = raw["value"].apply(lambda v: _scale_value(metric, v))

    real_rows = raw.dropna(subset=["value"])
    if real_rows.empty:
        return pd.DataFrame(columns=["date", "value", "series"])
    first_data = real_rows["date"].iloc[0]
    last_data = real_rows["date"].iloc[-1]
    visible_start = first_data - pd.Timedelta(days=2)
    raw = raw[(raw["date"] >= visible_start) & (raw["date"] <= last_data)].reset_index(drop=True)

    rolling = raw["value"].rolling(window=ROLLING_AVG_DAYS, center=True, min_periods=1).mean()

    rows: list[dict] = []
    for d, v in zip(raw["date"], raw["value"]):
        if pd.notna(v):
            rows.append({"date": d, "value": float(v), "series": "actual"})
    for d, v in zip(raw["date"], rolling):
        if pd.notna(v):
            rows.append({"date": d, "value": float(v), "series": "3-day avg"})

    if prior_model is not None and days is not None and prior_model.records:
        # Group prior records by their actual day and shift forward by ``days``
        # so the prior period overlays the current visible window. Bypass
        # ``time_series_by_day`` because it always anchors to "today" — prior
        # records sit in the *previous* window and don't survive that anchor.
        from collections import defaultdict as _dd
        by_day: dict = _dd(list)
        for r in prior_model.records:
            d = datetime.fromisoformat(r.timestamp).date()
            by_day[d].append(r)
        for d, recs in by_day.items():
            v = METRIC_GETTERS[metric](DashboardModel(recs))
            if v is None:
                continue
            shifted = pd.to_datetime(d) + pd.Timedelta(days=days)
            if shifted < visible_start or shifted > last_data:
                continue
            rows.append({
                "date": shifted, "value": float(_scale_value(metric, v)),
                "series": "prior",
            })

    return pd.DataFrame(rows)


def _monitoring_since(df: pd.DataFrame) -> str:
    """Earliest real data point in the trimmed dataframe — drives the
    'monitoring since' annotation under each chart."""
    if df.empty:
        return ""
    real = df[df["series"].isin(["actual", "3-day avg"])]
    if real.empty:
        return ""
    return _fmt_date(real["date"].min())


def render_trend_plot(
    model: DashboardModel,
    metric: str,
    days: int | None,
    *,
    prior_model: DashboardModel | None = None,
    height: int = 220,
) -> Figure:
    """Matplotlib trend plot — status-coloured trend line + visible point
    markers, monitoring-since caption baked in. Returns the Figure for
    rendering inside ``gr.Plot``.

    Uses ``matplotlib.figure.Figure`` directly (not ``plt.subplots``) so
    figures don't accumulate in the pyplot global registry across the many
    chart renders this dashboard does."""
    df = chart_dataframe(model, metric, days=days, prior_model=prior_model)

    # Wider canvas (10 inches) so the chart fills its card. ``dpi=200`` so the
    # rasterised PNG that gr.Plot ships to the browser stays sharp when
    # zoomed in (operator directive — chart rendering looked low-res before).
    # Effective output: 10in × 200dpi = 2000px wide; downscales cleanly into
    # any container width.
    fig = Figure(figsize=(10, height / 100), dpi=200, facecolor="#1c1c20")
    ax = fig.add_subplot(111)
    ax.set_facecolor("#1c1c20")
    if df.empty:
        ax.text(0.5, 0.5, "no data", ha="center", va="center",
                color="#5a5a64", transform=ax.transAxes, fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
    else:
        # Status of the headline value drives the colour of both series.
        value = METRIC_GETTERS[metric](model)
        status = metric_status(metric, value) if metric in THRESHOLDS else None
        actual_color, trend_color = _STATUS_CHART_COLOR.get(status, _STATUS_CHART_COLOR[None])

        actual_df = df[df["series"] == "actual"]
        trend_df = df[df["series"] == "3-day avg"]
        prior_df = df[df["series"] == "prior"]

        if not trend_df.empty:
            ax.plot(trend_df["date"], trend_df["value"],
                    color=trend_color, linewidth=1.4, zorder=2)
        if not actual_df.empty:
            # Markers visibly larger than the line so the operator can see
            # where real data exists vs where the trend is interpolated.
            ax.scatter(actual_df["date"], actual_df["value"],
                       color=trend_color, s=44, zorder=3,
                       edgecolor="#0a0a0a", linewidth=0.8)
        if not prior_df.empty:
            ax.plot(prior_df["date"], prior_df["value"],
                    color=_PRIOR_CHART_COLOR, linewidth=1.0,
                    linestyle="--", zorder=1, alpha=0.7)

    # Style — Midnight Mono palette
    ax.tick_params(colors="#9999a3", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#1f1f24")
    ax.set_ylabel(_y_axis_title(metric), color="#9999a3", fontsize=9)
    ax.grid(True, color="#1f1f24", linewidth=0.5)

    if not df.empty:
        # ``%-d`` drops the leading zero — "May 3" not "May 03" (operator
        # directive). On Windows the equivalent is ``%#d``; on POSIX (mac /
        # linux) ``%-d`` is correct.
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))

    # Coloured caption — colour-match the labels to the threshold lines'
    # implied colours (healthy = green, warning = amber, rest in muted).
    threshold_caption = _threshold_caption(metric)
    monitoring_since = _monitoring_since(df)
    if threshold_caption:
        # Split "healthy ≤ X · warning ≤ Y" into colored segments.
        # Render with multiple fig.text calls so each chunk gets its own colour.
        x = 0.015
        y = 0.02
        spacing = 0.006  # between segments
        for chunk, color in _caption_chunks(threshold_caption):
            t = fig.text(x, y, chunk, color=color, fontsize=8,
                         family="monospace")
            # Render then measure to advance x for the next chunk.
            fig.canvas.draw_idle()  # ensures bbox is computed
            try:
                bbox = t.get_window_extent(renderer=fig.canvas.get_renderer())
                x += bbox.width / fig.bbox.width + spacing
            except Exception:
                x += 0.18  # fallback
        if monitoring_since:
            fig.text(x, y, f"·  monitoring since {monitoring_since}",
                     color="#5a5a64", fontsize=8, family="monospace")
    elif monitoring_since:
        fig.text(0.015, 0.02, f"monitoring since {monitoring_since}",
                 color="#5a5a64", fontsize=8, family="monospace")

    fig.tight_layout(rect=[0, 0.08, 1, 1])
    return fig


def _caption_chunks(caption: str) -> list[tuple[str, str]]:
    """Split the threshold caption into ``(chunk, colour)`` pairs so each
    segment can be rendered in matplotlib with its own colour.

    Caption shape: ``healthy ≤ 10.0%  ·  warning ≤ 15.0%`` — split on the
    ``  ·  `` separator and colour the leading word per token."""
    chunks: list[tuple[str, str]] = []
    parts = caption.split("  ·  ")
    for i, part in enumerate(parts):
        prefix_color = "#5a5a64"
        if part.startswith("healthy"):
            prefix_color = "#34d399"
        elif part.startswith("warning"):
            prefix_color = "#fbbf24"
        if i > 0:
            chunks.append(("·  ", "#5a5a64"))
        chunks.append((part + "  ", prefix_color))
    return chunks


def _threshold_caption(metric: str) -> str:
    """Threshold portion of the chart caption — replaces the legend."""
    t = THRESHOLDS.get(metric)
    if t is None:
        return ""
    if t.unit == "pp":
        h = f"{t.healthy * 100:.1f}%"
        w = f"{t.warning * 100:.1f}%"
    elif t.unit == "ms":
        # Display threshold values in seconds to match the seconds-only Y-axis.
        h = f"{t.healthy / 1000:.2f} s"
        w = f"{t.warning / 1000:.2f} s"
    else:
        h = f"{t.healthy:.1f}"
        w = f"{t.warning:.1f}"
    direction = "≥" if t.higher_is_better else "≤"
    return f"healthy {direction} {h}  ·  warning {direction} {w}"


def _chart_caption(metric: str, df: pd.DataFrame) -> str:
    """Combined caption: threshold annotation + 'monitoring since' note."""
    parts: list[str] = []
    threshold = _threshold_caption(metric)
    if threshold:
        parts.append(threshold)
    since = _monitoring_since(df)
    if since:
        parts.append(f"monitoring since {since}")
    return "  ·  ".join(parts)


def format_trend_header(
    metric: str,
    model: DashboardModel,
    prior_model: DashboardModel | None = None,
) -> str:
    """Inline header above each chart — pure HTML so it can sit inside the
    chart-card wrapper without markdown getting passed through unparsed."""
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
    return f"<b>{label}:</b> {coloured}{delta}"


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
    """Build a DashboardModel from the log + cross-reference contacts.jsonl.

    The cross-referenced session IDs feed `contact_conversion_rate` so the
    metric reads true conversion (not the broken record-level intersection
    that always returned 0%; see contact_log.read_provided_session_ids
    docstring for the writer-order bug)."""
    provided = frozenset(read_provided_session_ids())
    return (
        DashboardModel(reader.read(), provided_session_ids=provided),
        datetime.now(timezone.utc),
    )


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
        # Page header — eyebrow + title + monospace metadata line on one
        # row; ghost Refresh button anchored top-right.
        with gr.Row(elem_classes=["page-header"]):
            with gr.Column(scale=4):
                gr.Markdown(
                    "<div class='eyebrow'>Digital Twin</div>"
                    "<div class='page-title'>Sentinel</div>"
                )
                header_md = gr.Markdown(
                    f"<div class='page-meta'>{format_header(source, loaded_at)}</div>"
                )
            with gr.Column(scale=0, elem_classes=["ghost-button"]):
                refresh_btn = gr.Button("Refresh", size="sm", scale=0)
        banner_md = gr.Markdown(_autorefresh_banner(refresh_messages))
        status_md = gr.Markdown(format_status_banner(_status_summary(headline_model)))

        with gr.Tabs() as tabs:
            # ---- Metrics tab ----------------------------------------------
            with gr.Tab("Metrics", id=TAB_METRICS):
                gr.Markdown("## Flags")
                flags_md = gr.Markdown(format_flags_summary(_build_flags(model)))

                gr.Markdown("## Health overview")
                metrics_md = gr.Markdown(
                    format_metrics_overview(models, priors, DISPLAY_MODE_DEFAULT)
                )

            # ---- Trends tab -----------------------------------------------
            with gr.Tab("Trends", id=TAB_TRENDS):
                gr.Markdown("## Trend Explorer")

                selected_metric = gr.State(None)
                scan_buttons: dict[str, gr.Button] = {}
                scan_charts: dict[str, gr.Plot] = {}
                scan_headers: dict[str, gr.Markdown] = {}

                with gr.Column(visible=True) as scan_view:
                    for block_name, block_metrics in THEMATIC_BLOCKS.items():
                        gr.Markdown(
                            f"<div class='section-header'>{block_name}</div>"
                        )
                        # Outcome jams 5 charts — chunk into 2-per-row so each
                        # chart has room for axis labels (operator directive).
                        per_row = 2 if block_name == "Outcome" else len(block_metrics)
                        for chunk_start in range(0, len(block_metrics), per_row):
                            chunk = block_metrics[chunk_start:chunk_start + per_row]
                            with gr.Row():
                                for metric in chunk:
                                    with gr.Column(min_width=320, elem_classes=["chart-card"]):
                                        scan_headers[metric] = gr.Markdown(
                                            f"<div class='chart-header'>{format_trend_header(metric, model)}</div>"
                                        )
                                        scan_charts[metric] = gr.Plot(
                                            value=render_trend_plot(model, metric, days=30),
                                            show_label=False,
                                        )
                                        with gr.Row(elem_classes=["investigate-link"]):
                                            scan_buttons[metric] = gr.Button(
                                                "investigate ↗", size="sm",
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
                    investigate_chart = gr.Plot(
                        value=None, show_label=False,
                    )
                    back_to_scan_btn = gr.Button("Back to scan", variant="secondary")

            # ---- Failures tab ---------------------------------------------
            with gr.Tab("Failures", id=TAB_FAILURES):
                gr.Markdown(
                    "<div class='section-header'>Failure Feed</div>"
                )
                with gr.Row(elem_classes=["filter-bar"]):
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

                # Wrap feed area in a column we can hide when the session view
                # opens — keeps the operator's focus on one thing at a time and
                # makes "Back to feed" return them to the feed (with
                # scroll_to_output ensuring the scroll position lands here).
                with gr.Column(visible=True) as feed_view:
                    feed_summary_md = gr.Markdown(
                        format_feed_summary(
                            initial_failures,
                            failure_mode_counts(model.records),
                        )
                    )
                    feed_empty_md = gr.Markdown(
                        "" if initial_failures
                        else "<div class='feed-empty'>No failures match the current filters.</div>"
                    )

                    feed_accordions: list[gr.Accordion] = []
                    feed_drilldowns: list[gr.Markdown] = []
                    feed_session_btns: list[gr.Button] = []
                    feed_session_states: list[gr.State] = []
                    for i in range(MAX_FEED_ROWS):
                        if i < len(initial_failures):
                            row = initial_failures[i]
                            label = _failure_accordion_label(row)
                            body_md = format_failure_drilldown(row.record)
                            sid = row.record.session_id
                            visible = True
                            mode_class = row.failure_mode
                        else:
                            label = ""
                            body_md = ""
                            sid = None
                            visible = False
                            mode_class = "gap"
                        with gr.Accordion(
                            label=label, open=False, visible=visible,
                            elem_classes=["feed-row", f"sev-{mode_class}"],
                        ) as acc:
                            feed_drilldowns.append(gr.Markdown(body_md))
                            feed_session_btns.append(
                                gr.Button("View full session", size="sm", variant="secondary")
                            )
                        feed_accordions.append(acc)
                        feed_session_states.append(gr.State(sid))

                with gr.Column(visible=False) as session_view:
                    session_md = gr.Markdown("")
                    back_btn = gr.Button("← Back to feed", variant="secondary")

                gr.Markdown("<div class='section-header'>Gap Clusters</div>")
                cluster_md = gr.Markdown(
                    format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH))
                )

                gr.Markdown("<div class='section-header'>Deflection summary</div>")
                deflection_md = gr.Markdown(
                    format_deflection_panel(read_summary("deflection", DEFAULT_SUMMARIES_DIR))
                )

        # ---- Wiring ---------------------------------------------------------

        def _feed_accordion_updates(rows: list[FailureRow]):
            """Build (accordion-update, drilldown-update, session-state-value) per slot.

            Note: Gradio's gr.update doesn't support changing elem_classes
            after construction, so the severity stripe is fixed at build
            time. The label still updates per-row to reflect the current
            filter — accepting that the stripe colour may not match the
            slot's content after a filter change. Acceptable trade-off given
            how the operator scans (severity-sorted; alerts always at the
            top in slots that were originally alert-coloured)."""
            acc_updates, body_updates, state_values = [], [], []
            for i in range(MAX_FEED_ROWS):
                if i < len(rows):
                    row = rows[i]
                    acc_updates.append(gr.update(
                        visible=True, label=_failure_accordion_label(row), open=False,
                    ))
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
            acc_updates, body_updates, state_values = _feed_accordion_updates(failure_rows)
            empty_html = (
                "" if failure_rows
                else "<div class='feed-empty'>No failures match the current filters.</div>"
            )
            feed_summary_html = format_feed_summary(
                failure_rows, failure_mode_counts(records),
            )
            return [
                f"<div class='page-meta'>{format_header(source, new_loaded_at)}</div>",
                _autorefresh_banner([cluster_msg, summary_msg]),
                format_status_banner(_status_summary(headline)),
                format_flags_summary(flags),
                format_metrics_overview(new_models, new_priors, DISPLAY_MODE_DEFAULT),
                feed_summary_html,
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
                metrics_md,
                feed_summary_md,
                feed_empty_md,
                *feed_accordions,
                *feed_drilldowns,
                *feed_session_states,
                cluster_md, deflection_md,
            ],
        )

        # Failure feed filter changes → re-populate accordions + summary
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
                format_feed_summary(rows, failure_mode_counts(records)),
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
                    feed_summary_md,
                    feed_empty_md,
                    *feed_accordions,
                    *feed_drilldowns,
                    *feed_session_states,
                ],
            )

        # View full session (per-row buttons) — hide the feed column, show
        # session-view column, and use scroll_to_output so the page scrolls
        # to the session_md (the first output) on click.
        def _make_session_click(slot_index: int):
            def _handler(session_id):
                if not session_id:
                    return gr.update(), gr.update(), gr.update()
                sessions = group_by_session(reader.read())
                match = next((s for s in sessions if s.session_id == session_id), None)
                if match is None:
                    return gr.update(), gr.update(), gr.update()
                return (
                    format_session_view(match),
                    gr.update(visible=False),
                    gr.update(visible=True),
                )
            return _handler

        for i, btn in enumerate(feed_session_btns):
            btn.click(
                fn=_make_session_click(i),
                inputs=[feed_session_states[i]],
                outputs=[session_md, feed_view, session_view],
                scroll_to_output=True,
            )

        def _back_to_feed():
            # Returning feed_view first (truthy update) so scroll_to_output
            # lands the operator back at the top of the failure feed.
            return gr.update(visible=True), gr.update(visible=False)

        back_btn.click(
            fn=_back_to_feed,
            outputs=[feed_view, session_view],
            scroll_to_output=True,
        )

        # Trend Explorer: investigate-mode renderer
        def _build_investigate_figure(metric, window_label, show_prior):
            if not metric:
                return gr.update(), None
            days = dict(TREND_WINDOWS).get(window_label, 30)
            current_records, _ = _load(reader)
            prior = current_records.for_prior_window(days=days) if show_prior else None
            fig = render_trend_plot(
                current_records, metric, days=days,
                prior_model=prior, height=480,
            )
            title = (
                f"### Investigating: {METRIC_LABELS.get(metric, metric)}\n"
                + format_trend_header(metric, current_records, prior_model=prior)
            )
            return title, fig

        def _enter_investigate_for(metric: str):
            def _handler(window_label, show_prior):
                title, fig = _build_investigate_figure(metric, window_label, show_prior)
                return (
                    metric,
                    gr.update(visible=False),
                    gr.update(visible=True),
                    title,
                    fig,
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
            title, fig = _build_investigate_figure(metric, window_label, show_prior)
            return title, fig

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

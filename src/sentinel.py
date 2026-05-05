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
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import gradio as gr
import matplotlib

matplotlib.use("Agg")  # non-interactive backend — no display needed
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
import canary_runner
import summarize_failures
from canary_baseline import (
    DEFAULT_BASELINE_PATH,
    read_baseline,
    resolve_baseline_records,
    runs_after_baseline,
)
from canary_corpus import DEFAULT_CORPUS_PATH, load_canaries
from canary_drift import (
    CanaryDriftFlag,
    aggregate_question,
    detect_drift,
    stratified_summary,
)
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
    tier_for_mode,
)
from interaction_log import InteractionRecord
from kb_corpus import CoverageEntry, compute_coverage, load_sections
from log_reader import HFReader, LocalReader, LogReader
from metric_status import (
    THRESHOLDS,
    TIER_B_METRICS,
    WoWDelta,
    metric_status,
    shift_status,
    tier_of,
    wow_delta,
)


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

# Minimum data span before WoW deltas carry semantic colour. With <14 days of
# log history a 'prior week' baseline is just a slice of the same chunk of
# data — colouring it green/red implies a real comparison that doesn't exist.
MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA = 14

# Tab identifiers so flag-click handlers can switch tabs by ID.
TAB_METRICS = "tab-metrics"
TAB_TRENDS = "tab-trends"
TAB_CANARY = "tab-canary"
TAB_FAILURES = "tab-failures"
TAB_KB_COVERAGE = "tab-kb-coverage"

# Sparklines render the last N canary runs as a tiny inline trend so each
# metric row carries its own trajectory cell. 12 fits the natural cadence:
# one weekly run × ~3 months of history.
CANARY_SPARK_WINDOW = 12

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
    font-size: 0.85em; font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.1em; text-transform: uppercase;
    padding-bottom: 4px;
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

/* Severity-driven row treatment — every severity gets the same density
   (8px padding, 4px margin, 3px ribbon, tinted background); only the
   ribbon colour + bg hue differ between severities. Subtle label tweaks
   (alert bolder, healthy muted) preserve a soft hierarchy without
   breaking the consistent bg-style the operator asked for. */
.metric-row.row-alert,
.metric-row.row-warning,
.metric-row.row-orientation,
.metric-row.row-healthy {
    padding-top: 8px;
    padding-bottom: 8px;
    margin: 4px 0;
    border-left-width: 3px;
}
.metric-row.row-alert {
    background: rgba(248, 113, 113, 0.06);
    border-left-color: var(--alert);
}
.metric-row.row-alert .metric-label {
    font-weight: 500;
}
.metric-row.row-warning {
    background: rgba(251, 191, 36, 0.06);
    border-left-color: var(--warning);
}
.metric-row.row-orientation {
    background: rgba(153, 153, 163, 0.05);
    border-left-color: var(--text-muted);
}
.metric-row.row-healthy {
    background: rgba(52, 211, 153, 0.06);
    border-left-color: var(--healthy);
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

/* Whole flag card is clickable — single full-width gr.Button styled to
   look like the prior card. Alert-tinted background, alert ribbon on the
   left, headline-first-line in alert colour, detail in text-secondary.

   Gradio's secondary button class chain has high specificity, so we
   - set the theme CSS variables on the wrapper (cascades into the inner
     button and wins because it's the same property the framework reads)
   - prefix with `.gradio-container` and stack `:not()` selectors to clear
     Gradio's `.lg.secondary.svelte-XXX` specificity for the layout rules
   - override every alignment-related property on the inner span as well
     (Gradio wraps the label text in a span that centres + collapses `\n`).
*/
.flag-button {
    /* Neon-red palette — saturated tint that reads as urgent on the dark
       dashboard. Local to flag cards; doesn't change the global --alert
       colour used elsewhere (status banner, metric badges, ribbons). */
    --flag-neon: #ff1f4e;
    --flag-neon-bright: #ff3a64;
    --flag-bg:    rgba(255, 31, 78, 0.20);
    --flag-bg-hover: rgba(255, 31, 78, 0.32);
    --button-secondary-background-fill: var(--flag-bg) !important;
    --button-secondary-background-fill-hover: var(--flag-bg-hover) !important;
    --button-secondary-text-color: var(--text-secondary) !important;
    --button-secondary-text-color-hover: var(--text-primary) !important;
    --button-secondary-border-color: rgba(255, 31, 78, 0.4) !important;
    --button-secondary-border-color-hover: var(--flag-neon-bright) !important;
    --button-secondary-shadow: none !important;
    --button-secondary-shadow-active: none !important;
    --button-secondary-shadow-hover: none !important;
    --button-shadow: none !important;
    --button-shadow-active: none !important;
    --button-shadow-hover: none !important;
}
.gradio-container .flag-button button,
.gradio-container .flag-button button:not(.tertiary):not(.icon):not(.disabled) {
    display: block !important;
    width: 100% !important;
    background: var(--flag-bg) !important;
    background-color: var(--flag-bg) !important;
    border: 1px solid rgba(255, 31, 78, 0.4) !important;
    border-left: 3px solid var(--flag-neon) !important;
    border-radius: 3px !important;
    padding: 12px 16px !important;
    margin: 4px 0 !important;
    color: var(--text-secondary) !important;
    font-size: 0.92em !important;
    font-weight: 400 !important;
    line-height: 1.55 !important;
    text-align: left !important;
    white-space: pre-line !important;
    cursor: pointer !important;
    box-shadow: none !important;
    transition: background 0.12s ease, border-color 0.12s ease !important;
}
.gradio-container .flag-button button > *,
.gradio-container .flag-button button > span,
.gradio-container .flag-button button > div {
    display: block !important;
    width: 100% !important;
    text-align: left !important;
    white-space: pre-line !important;
    color: inherit !important;
    font-size: inherit !important;
    font-weight: inherit !important;
    line-height: inherit !important;
    background: transparent !important;
    margin: 0 !important;
    padding: 0 !important;
}
.gradio-container .flag-button button:hover,
.gradio-container .flag-button button:not(.tertiary):hover {
    background: var(--flag-bg-hover) !important;
    background-color: var(--flag-bg-hover) !important;
    border-color: var(--flag-neon-bright) !important;
    border-left-color: var(--flag-neon-bright) !important;
    color: var(--text-primary) !important;
}
.gradio-container .flag-button button::first-line,
.gradio-container .flag-button button:not(.tertiary)::first-line {
    font-size: 1.08em !important;
    font-weight: 700 !important;
    color: var(--flag-neon-bright) !important;
}

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
.feed-summary.failures {
    padding-bottom: 8px;
}
.feed-summary.outcomes {
    padding-top: 4px;
    border-top: 1px dashed var(--border);
}
.feed-summary .feed-section-heading {
    font-weight: 700;
    color: var(--text-primary);
    margin-right: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.85em;
}
.feed-summary.failures .feed-section-heading {
    color: var(--alert);
}
.feed-summary.outcomes .feed-section-heading {
    color: var(--text-secondary);
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
   into the background); deflected = teal (informational, parked at lowest
   severity — surfaced for pattern-spotting on out-of-scope redirects). */
.feed-summary .feed-summary-mode.refused                  { color: #f87171; }
.feed-summary .feed-summary-mode.retry-exhausted          { color: #fb923c; }
.feed-summary .feed-summary-mode.rejected-then-recovered  { color: #fbbf24; }
.feed-summary .feed-summary-mode.gap                      { color: #60a5fa; }
.feed-summary .feed-summary-mode.deflected                { color: #2dd4bf; }

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

/* ---- Canary tab ---- */
.canary-banner {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.92em;
    color: var(--text-secondary);
    padding: 10px 14px;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    margin: 6px 0 16px;
}
.canary-banner .count-alert    { color: var(--alert);   font-weight: 600; }
.canary-banner .count-warning  { color: var(--warning); font-weight: 600; }
.canary-empty {
    padding: 18px;
    color: var(--text-secondary);
    background: var(--bg-surface);
    border: 1px dashed var(--border-strong);
    border-radius: 4px;
    text-align: center;
    font-size: 0.92em;
}
.canary-drift-card {
    padding: 12px 14px;
    margin: 6px 0;
    border-radius: 4px;
    border-left: 3px solid var(--alert);
    background: var(--alert-tint);
}
.canary-drift-card.sev-warning {
    border-left-color: var(--warning);
    background: var(--warning-tint);
}
.canary-drift-headline {
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 4px;
}
.canary-drift-detail {
    font-size: 0.88em;
    color: var(--text-secondary);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
.canary-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88em;
    margin-top: 8px;
}
.canary-table th, .canary-table td {
    text-align: left;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
}
.canary-table th {
    color: var(--text-secondary);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.78em;
}
.canary-row.sev-major { background: var(--alert-tint); }
.canary-row.sev-minor { background: var(--warning-tint); }
.canary-sev { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
.canary-rebaseline-warning {
    color: var(--text-secondary);
    font-size: 0.88em;
    background: var(--warning-tint);
    border-left: 3px solid var(--warning);
    padding: 10px 14px;
    border-radius: 3px;
    margin: 4px 0 10px;
}

/* Canary health sections — same .section-block + .metric-row visual
   language as the Metrics tab. Post-#51 the trajectory view renders 5
   columns (Metric | Benchmark | +1 | +2 | +3) instead of the pre-#51
   (Metric | Current | Δ baseline) shape. */
.canary-section { margin: 8px 0; }
.metric-row.canary-row {
    grid-template-columns: 2.4fr repeat(4, 1fr);
}
.canary-row .metric-suffix {
    margin-left: 8px;
    font-style: italic;
}
.canary-row .canary-delta-cell .delta {
    font-size: 0.88em;
}

/* Stratified summary chips */
.canary-stratified {
    margin: 4px 0 14px;
    font-size: 0.88em;
    line-height: 1.8;
}
.canary-stratified-label {
    color: var(--text-secondary);
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-right: 8px;
}
.canary-chip {
    display: inline-block;
    padding: 2px 8px;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.85em;
    color: var(--text-secondary);
    margin: 2px 1px;
}
.canary-chip strong {
    color: var(--text-primary);
    margin-left: 4px;
}
.canary-stratified-empty {
    color: var(--text-muted);
    font-size: 0.88em;
    font-style: italic;
    margin: 4px 0 12px;
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

/* ---- Section header hierarchy ----
   Two levels:
   - .section-header-major — top-of-tab landmarks (Flags, Health overview,
     Failure Feed, Gap Clusters, Deflection summary; KB Source Coverage
     lives on its own tab post-Session 50).
     Reads as "you've entered a new area."
   - .section-header — sub-section inside a major area (Outcome, Routing,
     Engagement, Tool use, Latency under Health overview; the per-block
     groupings under Trend Explorer's scan mode).
*/
.section-header-major {
    font-size: 20px; font-weight: 700;
    letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--text-primary);
    margin: 36px 0 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border-strong);
}
.section-header-major:first-of-type { margin-top: 12px; }
.section-header {
    font-size: 13px; font-weight: 600;
    letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--text-secondary);
    margin: 24px 0 10px;
    padding-bottom: 5px;
    border-bottom: 1px solid var(--border);
}
.section-header:first-of-type { margin-top: 8px; }

/* Latency stages — p50 muted, p95 primary, share muted; pipe sep dim.
   Labels (p50 / p95 / share) appear once in the section caption above. */
.metric-row .latency-p50   { color: var(--text-secondary); }
.metric-row .latency-p95   { color: var(--text-primary); font-weight: 500; }
.metric-row .latency-share { color: var(--text-secondary); }
.metric-row .latency-sep   { color: var(--text-muted); }

/* Section caption — sits between the section header and the rows. Used by
   Latency to label the tri-tuple (p50 | p95 | share) once at the top. */
.section-caption {
    color: var(--text-muted);
    font-size: 11px;
    letter-spacing: 0.04em;
    margin: -8px 0 6px;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}

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

/* Shared branch legend — single strip at the top of the Trends tab.
   Five colour swatches + branch names, monospace, compact. */
.branch-legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 14px 22px;
    margin: 0 0 18px;
    padding: 10px 14px;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 4px;
}
.branch-legend .legend-label {
    font-size: 0.72em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted);
    margin-right: 8px;
}
.branch-legend .branch-swatch {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.85em;
    color: var(--text-secondary);
}
.branch-legend .swatch-color {
    width: 12px;
    height: 12px;
    border-radius: 2px;
    display: inline-block;
}

/* ---- Filter bar (Failures) — single 36px row ---- */
.filter-bar { gap: 8px !important; }
.filter-bar .gradio-dropdown,
.filter-bar .gradio-textbox { min-height: 36px !important; }

/* ---- KB coverage panel (Failures tab) ---- */
.kb-coverage-summary {
    padding: 8px 0 12px;
    color: var(--text-secondary);
    font-size: 0.92em;
    display: flex; gap: 16px; flex-wrap: wrap;
}
.kb-coverage-summary .kb-cov-count {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
.kb-coverage-summary .kb-cov-count.never     { color: var(--alert); }
.kb-coverage-summary .kb-cov-count.retrieved { color: var(--text-primary); }
.kb-coverage-summary .kb-cov-count.off-canon { color: var(--warning); }
.kb-cov-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 8px;
    margin-top: 4px;
}
.kb-cov-card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-left: 3px solid transparent;
    border-radius: 4px;
    padding: 8px 12px;
}
.kb-cov-card.never     { border-left-color: var(--alert); }
.kb-cov-card.retrieved { border-left-color: var(--healthy); }
.kb-cov-card.off-canon { border-left-color: var(--warning); }
.kb-cov-header {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 2px;
}
.kb-cov-label {
    font-weight: 500; color: var(--text-primary); font-size: 0.92em;
}
.kb-cov-chip {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.78em;
    color: var(--text-muted);
    background: var(--bg-base);
    padding: 1px 8px;
    border-radius: 4px;
}
.kb-cov-chip.never { color: var(--alert); }
.kb-cov-meta {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.78em;
    color: var(--text-muted);
}

/* ---- Glossary (Metrics tab, bottom, collapsed by default) ---- */
.glossary { padding: 4px 0 8px; }
.glossary-section-header {
    font-size: 12px; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--text-secondary);
    margin: 14px 0 6px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--border);
}
.glossary-section-header:first-child { margin-top: 4px; }
.glossary-row {
    display: grid;
    grid-template-columns: 280px 1fr;
    column-gap: 14px;
    padding: 4px 2px;
    align-items: baseline;
}
.glossary-row .glossary-name {
    color: var(--text-primary);
    font-size: 0.92em;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
.glossary-row .glossary-desc {
    color: var(--text-secondary);
    font-size: 0.92em;
    line-height: 1.45;
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


def _fmt_latency_row(p: dict) -> str:
    """Three-column latency cell — values only; the per-column labels (p50 |
    p95 | share) appear once in the section caption above the rows.

    p50 muted, p95 primary, share muted. The label-once design keeps each
    cell short enough to fit the 4-window grid without truncation."""
    p50 = _fmt_seconds(p.get("p50"))
    p95 = _fmt_seconds(p.get("p95"))
    share_v = p.get("share")
    share = EM_DASH if share_v is None else f"{share_v * 100:.0f}%"
    sep = "<span class='latency-sep'> | </span>"
    return (
        f"<span class='latency-p50'>{p50}</span>{sep}"
        f"<span class='latency-p95'>{p95}</span>{sep}"
        f"<span class='latency-share'>{share}</span>"
    )


def _fmt_attempts_distribution(d: dict[str, float]) -> str:
    """Inline distribution: ``1: 75% · 2: 18% · 3: 7%`` — same compact
    pattern as branch_distribution."""
    if not d:
        return EM_DASH
    return " · ".join(f"{k}: {v * 100:.0f}%" for k, v in d.items())


# ---- Threshold-aware rendering helpers --------------------------------------


def _status_class(metric_name: str | None, value: float | None) -> str:
    """CSS class for the metric value cell — drives the colour treatment.

    Only Tier A (value-on-band) drives per-cell colour; Tier B's shift
    status is row-level (the per-cell values are context for the shift, not
    independently classifiable as healthy/warning/alert). Tier C / unknown
    → no class. Post-#48 tier framework."""
    if metric_name is None:
        return ""
    if tier_of(metric_name) != "A":
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
    # Tier A — value-on-band
    "refusal_rate":                 "Refused to answer",
    "retry_exhausted_rate":         "Retries exhausted",
    "contact_conversion_rate":      "Contact form submitted",
    "tool_call_success_rate":       "Tool calls succeeded",
    "latency_p95_total":            "Slow responses",
    # Tier B — shift-on-band (banner reads "shifted" semantically; same
    # plain-language label, but the badge is shift-driven)
    "gap_rate":                     "Unknown answers",
    "deflection_rate":              "Deflected to story",
    "guardrail_rejection_rate":     "Quality-check rejections",
    "low_confidence_rate":          "Uncertain classifications",
    "mean_classification_confidence": "Classifier confidence",
    "answered_with_substance_rate": "Substantive answers",
    "mean_turns_per_session":       "Avg questions per session",
    "turns_per_session_median":     "Conversation depth",
    "contact_offer_rate":           "Contact form offered",
    "technical_tool_call_rate":     "Tool calls per TECHNICAL turn",
}


def _status_summary(model: DashboardModel) -> dict[str, list[str]]:
    """Aggregate metric statuses into 3 buckets for the page-level banner.

    Returns ``{"alert": [...], "warning": [...], "healthy": [...]}`` of
    *friendly* metric labels (banner-readable, not technical).

    Combines two kinds of status (post-#48 tier framework):
    - **Tier A** (in `THRESHOLDS`): value-on-band against the headline
      window. Crossing band IS the failure event. Always evaluated.
    - **Tier B** (in `TIER_B_METRICS`): shift-on-band across the
      (7d↔30d) and (30d↔90d) window pairs. Worst of either comparison
      drives the bucket. Gated on ``history_days >=
      MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA`` (Session 54) — under 14 days
      of data the comparison is structurally noisy (windows overlap
      heavily), so Tier B is suppressed from the banner rather than
      firing cold-start spurious alerts.

    Tier C / unregistered metrics never appear in the banner — they're
    pure orientation reflections of system state."""
    buckets: dict[str, list[str]] = {"alert": [], "warning": [], "healthy": []}
    history_days = _data_history_days(model.records)
    tier_b_eligible = history_days >= MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA

    def _push(metric: str, status: str | None) -> None:
        if status is None:
            return
        buckets[status].append(
            FRIENDLY_BANNER_LABELS.get(metric, METRIC_LABELS.get(metric, metric))
        )

    for metric, getter in METRIC_GETTERS.items():
        t = tier_of(metric)
        if t == "A":
            _push(metric, metric_status(metric, getter(model)))
        elif t == "B" and tier_b_eligible:
            v_7 = getter(model.for_window(7))
            v_30 = getter(model.for_window(30))
            v_90 = getter(model.for_window(90))
            s = _worst_status([
                shift_status(v_7, v_30),
                shift_status(v_30, v_90),
            ])
            _push(metric, s)
        # Tier C / unknown: never surfaced in banner.
        # Tier B with insufficient history: suppressed (cold-start safety).
    return buckets


def _worst_status(statuses: list[str | None]) -> str | None:
    """Reduce a list of statuses to the worst (alert > warning > healthy).
    Returns None if every input is None."""
    s = [x for x in statuses if x is not None]
    if not s:
        return None
    if "alert" in s:
        return "alert"
    if "warning" in s:
        return "warning"
    return "healthy"


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
        ("Answered with substance",    "answered_with_substance_rate", lambda m: m.answered_with_substance_rate, _fmt_pct),
        ("Gap rate",                   "gap_rate",                    lambda m: m.gap_rate, _fmt_pct),
        ("Deflection rate",            "deflection_rate",             lambda m: m.deflection_rate, _fmt_pct),
        ("Refusal rate",               "refusal_rate",                lambda m: m.refusal_rate, _fmt_pct),
        ("Guardrail rejection rate",   "guardrail_rejection_rate",    lambda m: m.guardrail_rejection_rate, _fmt_pct),
        ("Retry-exhaustion rate",      "retry_exhausted_rate",        lambda m: m.retry_exhausted_rate, _fmt_pct),
        ("Attempts distribution",      None,                          lambda m: m.attempts_distribution, _fmt_attempts_distribution),
    ]),
    ("Routing", [
        ("Classifier branch distribution",         None,                          lambda m: m.branch_distribution, _fmt_branches),
        ("Classifier mean confidence",             "mean_classification_confidence", lambda m: m.mean_classification_confidence, lambda v: _fmt_num(v, 2)),
        ("Classifier mean confidence by branch",   None,                          lambda m: m.mean_confidence_by_branch, _fmt_branches),
        ("Classifier low-confidence rate (<0.7)",  "low_confidence_rate",         lambda m: m.low_confidence_rate(), _fmt_pct),
    ]),
    ("Engagement", [
        ("Unique sessions",            None,                          lambda m: m.unique_sessions, str),
        ("Avg questions per session",  "mean_turns_per_session",      lambda m: m.mean_turns_per_session, lambda v: _fmt_num(v, 2)),
        ("Turns/session (median)",     "turns_per_session_median",    lambda m: m.turns_per_session_median, _fmt_num),
        ("Contact-offer rate",         "contact_offer_rate",          lambda m: m.contact_offer_rate, _fmt_pct),
        ("Contact-conversion rate",    "contact_conversion_rate",     lambda m: m.contact_conversion_rate, _fmt_pct),
    ]),
    ("Tool use", [
        ("Tool calls (count)",         None,                          lambda m: m.tool_call_count, str),
        # technical_tool_call_rate is Tier B post-#48 — shift-detected,
        # not threshold-alerted. The denominator caveat (LIMITATIONS::P8)
        # is what kept it out of THRESHOLDS; the new tier framework is
        # explicit about it.
        ("Tool calls / TECHNICAL turn", "technical_tool_call_rate",   lambda m: m.technical_tool_call_rate, _fmt_pct),
        ("Tool-call success rate",     "tool_call_success_rate",      lambda m: m.tool_call_success_rate, _fmt_pct),
    ]),
    ("Latency", [
        ("classifier",                 None,                          lambda m: m.latency_with_share("classifier"), _fmt_latency_row),
        ("retrieval",                  None,                          lambda m: m.latency_with_share("retrieval"), _fmt_latency_row),
        ("generation",                 None,                          lambda m: m.latency_with_share("generation"), _fmt_latency_row),
        ("guardrail",                  None,                          lambda m: m.latency_with_share("guardrail"), _fmt_latency_row),
        ("total (p95)",                "latency_p95_total",           lambda m: m.latency_percentiles("total").get(95), _fmt_ms),
    ]),
]


# Per-section caption rendered between the section header and the rows.
# Used today only by Latency to label the per-cell tri-tuple (p50 | p95 |
# share) once at the top of the section, so each row's cell can render the
# values without redundant labels.
SECTION_CAPTIONS: dict[str, str] = {
    "Latency": "each cell: p50 | p95 | share of total p95",
}


# One-sentence description per row in METRIC_SPECS — surfaced via the
# collapsed Glossary accordion at the bottom of the Metrics tab. Keys must
# match the display labels in METRIC_SPECS exactly; a forcing-function test
# pins the two together so a label rename can't silently drop a description.
METRIC_GLOSSARY: dict[str, str] = {
    # Outcome
    "Total interactions":                                  "Count of all logged turns in the window — pure volume signal (Tier C).",
    "Answered with substance":                             "Share of turns the producer classified as substantive answers (event_type='answered'). Completes the 4-bucket Outcome partition: gap + deflected + refused + answered = 100%. Tier B — shift-detected.",
    "Gap rate":                                            "Share of turns where the system either acknowledged it didn't have the information (canonical gap phrase) or produced a structured gap-aware response about an absent skill. Tier B — shift-detected.",
    "Deflection rate":                                     "Share of turns where the system politely redirected an out-of-scope question (general coding help, trivia, opinions) rather than answering. Tier B — shift-detected.",
    "Refusal rate":                                        "Share of turns that bottomed out into the canned-refusal copy after 3 rejected guardrail attempts. Tier A — value alert (mechanism IS failure).",
    "Guardrail rejection rate":                            "Share of turns where the guardrail rejected at least one attempt — composite over fabrication, scope, tone, injection, dishonest gap. Tier B — shift-detected.",
    "Retry-exhaustion rate":                               "Share of turns that consumed all 3 generation attempts — superset of refusal_rate; the gap is barely-accepted turns. Tier A — value alert.",
    "Attempts distribution":                               "Share of turns by attempt count (1 / 2 / 3) — fills the middle between first-attempt-pass and retry-exhausted. MAX_ATTEMPTS=3 is the hard ceiling, so the bucket key is exact (no '3+'). Tier C — orientation chip.",
    # Routing
    "Classifier branch distribution":                      "Fraction of turns routed to each branch (GENERIC / GAP / TECHNICAL / BEHAVIOURAL / LOGISTICAL). Tier C — orientation chip.",
    "Classifier mean confidence":                          "Average classifier confidence across the window — direct read of how sure the classifier is on average. Tier B — shift-detected.",
    "Classifier mean confidence by branch":                "Per-branch mean confidence chip — actionable read for 'which branch is the classifier wobbling on?'. Tier C — orientation chip.",
    "Classifier low-confidence rate (<0.7)":               "Share of turns where the classifier itself flagged uncertainty — catches misroutes the classifier admits to. Tier B — shift-detected.",
    # Engagement
    "Unique sessions":                                     "Count of distinct chat sessions — volume orientation.",
    "Avg questions per session":                           "Mean turns per session — companion to the median, more sensitive to deeply-engaged outliers.",
    "Turns/session (median)":                              "Median chat depth — typical engagement signal; pair with contact_conversion before judging.",
    "Contact-offer rate":                                  "Fraction of turns where the contact form was visible — depends on traffic shape and trigger configuration.",
    "Contact-conversion rate":                             "Share of offered sessions that submitted the form — joined session-level on contacts.jsonl.",
    # Tool use
    "Tool calls (count)":                                  "Total fetch_project_readme invocations across the window — volume signal.",
    "Tool calls / TECHNICAL turn":                         "Rate of TECHNICAL turns that invoked at least one tool call — descriptive direction-of-change orientation, not a target. Denominator is all TECHNICAL turns (LIMITATIONS::P8); the canary tab carries the warranted-only counterpart.",
    "Tool-call success rate":                              "Fraction of tool invocations that returned successfully — should be ~100% for local file reads.",
    # Latency
    "classifier":                                          "p50 | p95 | share of total p95 for the classifier stage — typical 1s, p95 ≈ 1.7s; gpt-4.1-nano cached.",
    "retrieval":                                           "p50 | p95 | share of total p95 for the ChromaDB retrieval stage — sub-100ms typical; spikes signal embedding cache miss.",
    "generation":                                          "p50 | p95 | share of total p95 for the OpenAI generation stage — typical 3.5s; spikes correlate with retry rounds.",
    "guardrail":                                           "p50 | p95 | share of total p95 for the Anthropic guardrail stage — typical 5s; slower than the gpt-4.1 generator.",
    "total (p95)":                                         "End-to-end p95 latency — the headline operator-facing number across all stages.",
}


def format_metrics_glossary() -> str:
    """Glossary HTML — one row per metric, grouped by the same sections as
    METRIC_SPECS. Rendered inside a collapsed Accordion at the bottom of the
    Metrics tab so the operator can recall what each row means without
    leaving the dashboard."""
    parts: list[str] = []
    for section_name, specs in METRIC_SPECS:
        parts.append(
            f"<div class='glossary-section-header'>{html.escape(section_name)}</div>"
        )
        for spec in specs:
            label = spec[0]
            desc = METRIC_GLOSSARY.get(label, "")
            parts.append(
                "<div class='glossary-row'>"
                f"<span class='glossary-name'>{html.escape(label)}</span>"
                f"<span class='glossary-desc'>{html.escape(desc)}</span>"
                "</div>"
            )
    return "<div class='glossary'>" + "".join(parts) + "</div>"


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


def _row_severity(
    metric_name: str | None, raws: list, history_days: int = 0,
) -> str:
    """Worst per-row status — drives the row's visual treatment.

    Tier-aware (post-#48):
    - **Tier A:** worst per-window value-status across `raws` (a metric
      that's healthy on 7d but alerted on Global gets the alert row).
      Always evaluated — value-band semantics don't depend on data history.
    - **Tier B:** worst shift-status across (raws[0] vs raws[1]) and
      (raws[1] vs raws[2]). Gated on `history_days >=
      MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA` (Session 54) — under 14 days
      of data the comparison is structurally noisy (the windows overlap
      heavily), so Tier B falls through to orientation rather than firing
      cold-start spurious alerts. Mirrors the gate `_delta_inline` already
      applies to the WoW delta arrows.
    - **Tier C / unknown:** orientation (no badge).

    Worst-status ranking: alert > warning > healthy."""
    if metric_name is None:
        return "orientation"
    t = tier_of(metric_name)
    if t == "A":
        statuses = {metric_status(metric_name, v) for v in raws}
        if "alert" in statuses:
            return "alert"
        if "warning" in statuses:
            return "warning"
        if "healthy" in statuses:
            return "healthy"
        return "orientation"
    if t == "B":
        if len(raws) < 3:
            return "orientation"
        if history_days < MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA:
            return "orientation"
        s = _worst_status([
            shift_status(raws[0], raws[1]),
            shift_status(raws[1], raws[2]),
        ])
        return s or "orientation"
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
            severity = _row_severity(metric_name, raws, history_days=history_days)
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
        caption = SECTION_CAPTIONS.get(section_name, "")
        caption_html = (
            f"<div class='section-caption'>{html.escape(caption)}</div>"
            if caption else ""
        )
        blocks.append(
            f"<div class='section-header'>{section_name}</div>"
            f"{caption_html}"
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
    """Per-tier counts above the feed (Session 49 split).

    Two sub-section summaries: **Failures** (refused, retry-exhausted —
    modes where the metric IS the failure event) and **Outcomes**
    (rejected-then-recovered, gap, deflected — modes where the metric
    IS a system-output shape worth scanning, not a defect). Same data
    flow as before; the regrouping is display-only.

    Each sub-section: '{tier} · {N} total · {n} {friendly mode} · ...'
    with per-mode chips coloured by severity for at-a-glance scan.
    Sub-sections only render when their tier has ≥1 record."""
    total = len(rows)
    if total == 0:
        return ""
    from failure_feed import _SEVERITY_RANK as _MODE_RANK

    def _tier_block(tier: str, label: str, css_class: str) -> str:
        tier_modes = [m for m in counts if tier_for_mode(m) == tier]
        tier_total = sum(counts[m] for m in tier_modes)
        if tier_total == 0:
            return ""
        parts = [
            f"<span class='feed-section-heading'>{label}</span>",
            f"<span class='feed-summary-total'>{tier_total} total</span>",
        ]
        sorted_modes = sorted(tier_modes, key=lambda m: _MODE_RANK.get(m, 99))
        for mode in sorted_modes:
            n = counts[mode]
            if n == 0:
                continue
            friendly = FAILURE_MODE_LABELS.get(mode, mode).split(" (")[0]
            parts.append(
                f"<span class='feed-summary-mode {mode}'>{n} {html.escape(friendly)}</span>"
            )
        return f"<div class='feed-summary {css_class}'>" + "".join(parts) + "</div>"

    return _tier_block("failure", "Failures", "failures") + _tier_block("outcome", "Outcomes", "outcomes")


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


KB_COVERAGE_EMPTY_PLACEHOLDER = (
    "_No KB sections found — check that ``data/knowledge_base/*.md`` exists._"
)


def format_kb_coverage_panel(entries: list[CoverageEntry]) -> str:
    """Source coverage — every canonical KB section with its retrieval count
    in the window, sorted ascending. Never-retrieved sections surface first
    (alert ribbon); off-canon retrievals (embedded sections that no longer
    exist in source files) sit at the bottom as a drift signal."""
    if not entries:
        return KB_COVERAGE_EMPTY_PLACEHOLDER

    never_retrieved = [e for e in entries if not e.off_canon and e.retrieval_count == 0]
    retrieved = [e for e in entries if not e.off_canon and e.retrieval_count > 0]
    off_canon = [e for e in entries if e.off_canon]

    summary = (
        f"<div class='kb-coverage-summary'>"
        f"<span class='kb-cov-count never'>{len(never_retrieved)} never retrieved</span>"
        f"<span class='kb-cov-count retrieved'>{len(retrieved)} retrieved</span>"
        + (
            f"<span class='kb-cov-count off-canon'>{len(off_canon)} off-canon</span>"
            if off_canon else ""
        )
        + "</div>"
    )

    def _card(e: CoverageEntry, ribbon: str) -> str:
        count_chip = (
            f"<span class='kb-cov-chip never'>0</span>"
            if e.retrieval_count == 0 and not e.off_canon
            else f"<span class='kb-cov-chip'>{e.retrieval_count}</span>"
        )
        return (
            f"<div class='kb-cov-card {ribbon}'>"
            f"<div class='kb-cov-header'>"
            f"<span class='kb-cov-label'>{html.escape(e.section_heading)}</span>"
            f"{count_chip}"
            f"</div>"
            f"<div class='kb-cov-meta'>{html.escape(e.source_file)}</div>"
            f"</div>"
        )

    cards: list[str] = []
    for e in never_retrieved:
        cards.append(_card(e, "never"))
    for e in retrieved:
        cards.append(_card(e, "retrieved"))
    for e in off_canon:
        cards.append(_card(e, "off-canon"))

    return summary + "<div class='kb-cov-grid'>" + "".join(cards) + "</div>"


# ---- Flags panel ------------------------------------------------------------


FLAGS_EMPTY_PLACEHOLDER = (
    "_No anomalies detected — every detector returned no flags. Stable / quiet "
    "weeks render no flags by design._"
)

# Human-readable destination labels for flag click handlers — operator sees
# "→ Failures" not "→ failure_feed". Maps the FlagDetector targets onto
# the actual tab names (failure_feed and gap_clusters both live on Failures).
_FLAG_TARGET_LABEL: dict[str, str] = {
    "failure_feed": "Failures",
    "gap_clusters": "Failures",
    "trend": "Trends",
}


def format_flag_card(flag: Flag) -> str:
    """One flag card's HTML. Used by `build_app` to populate the per-flag
    slot rows."""
    headline = html.escape(flag.headline)
    detail = html.escape(flag.detail)
    return (
        "<div class='flag-card'>"
        f"<div class='flag-headline'>{headline}</div>"
        f"<div class='flag-detail'>{detail}</div>"
        "</div>"
    )


def format_flags_summary(flags: list[Flag]) -> str:
    """All flag cards joined into one HTML block. Kept for the empty-state
    rendering + as a back-compat surface for callers that only want the
    visual cards (no click handlers)."""
    if not flags:
        return FLAGS_EMPTY_PLACEHOLDER
    return "\n".join(format_flag_card(f) for f in flags)


CANARY_EMPTY_PLACEHOLDER = (
    "<div class='canary-empty'>"
    "No canary runs yet. Run "
    "<code>uv run python src/canary_runner.py</code> to populate."
    "</div>"
)

CANARY_NO_BASELINE = (
    "<div class='canary-empty'>"
    "No baseline frozen yet. Run the canary CLI with "
    "<code>--freeze-baseline</code> or use the Re-baseline button below."
    "</div>"
)


def _short_sha(sha: str | None) -> str:
    if not sha:
        return "—"
    return sha[:7]


def format_canary_drift_summary(
    pointer: dict | None,
    current_run_records: list[InteractionRecord],
    flags: list[CanaryDriftFlag],
) -> str:
    """One-row banner: flag counts + benchmark date + latest canary run date.

    Both dates carry their git_sha so drift attribution is one glance away
    (`from_sha → to_sha`)."""
    if not current_run_records:
        return CANARY_EMPTY_PLACEHOLDER
    major = sum(1 for f in flags if f.severity == "major")
    minor = sum(1 for f in flags if f.severity == "minor")
    current_sha = _short_sha(current_run_records[0].git_sha)
    latest_run_at = (current_run_records[0].timestamp or "")[:10]

    if pointer is None:
        return (
            "<div class='canary-banner'>"
            f"latest canary run {html.escape(latest_run_at)} on sha "
            f"<code>{current_sha}</code> · "
            "<em>no benchmark frozen — use "
            "<code>uv run python src/canary_runner.py --freeze-baseline</code> "
            "or the Re-baseline button below.</em>"
            "</div>"
        )

    baseline_sha = _short_sha(pointer.get("frozen_git_sha"))
    frozen_at = (pointer.get("frozen_at") or "")[:10]
    return (
        "<div class='canary-banner'>"
        f"<span class='count-alert'>{major} major</span> · "
        f"<span class='count-warning'>{minor} minor</span> · "
        f"benchmark {html.escape(frozen_at)} (<code>{baseline_sha}</code>) → "
        f"latest canary run {html.escape(latest_run_at)} "
        f"(<code>{current_sha}</code>)"
        "</div>"
    )


def _delta_cell(current: float | None, baseline: float | None,
                *, as_pct: bool = True, lower_is_better: bool = True) -> str:
    """`Δ baseline` cell — colour-coded delta. `lower_is_better=True` for
    rates / latency (delta>0 is degrading); `False` for things where higher
    is better (pass rate, outcome_accuracy)."""
    if current is None or baseline is None:
        return "<span class='delta'>—</span>"
    delta = current - baseline
    if abs(delta) < 1e-9:
        return "<span class='delta stable'>=</span>"
    is_degrading = (delta > 0) if lower_is_better else (delta < 0)
    cls = "delta degrading" if is_degrading else "delta improving"
    sign = "+" if delta > 0 else ""
    body = f"{sign}{delta * 100:.1f}pp" if as_pct else f"{sign}{delta:.0f}"
    return f"<span class='{cls}'>{body}</span>"


def _delta_ms(current: float | None, baseline: float | None) -> str:
    if current is None or baseline is None:
        return "<span class='delta'>—</span>"
    delta = current - baseline
    if abs(delta) < 1:
        return "<span class='delta stable'>=</span>"
    cls = "delta degrading" if delta > 0 else "delta improving"
    sign = "+" if delta > 0 else ""
    return f"<span class='{cls}'>{sign}{delta / 1000:+.2f}s</span>"


CANARY_TRAJECTORY_SLOTS = 3   # +1, +2, +3 post-baseline runs in the trajectory view
EM_DASH_CELL = "<span class='delta'>—</span>"


def _canary_metric_row(label: str, cells: list[str], *, suffix: str = "") -> str:
    """Render one canary trajectory row.

    `cells` is exactly ``1 + CANARY_TRAJECTORY_SLOTS`` formatted strings —
    [Benchmark, +1, +2, +3] — matching the 5-column grid post-#51. Empty
    slots should pre-render as ``EM_DASH_CELL`` so the row layout doesn't
    collapse when fewer than 3 post-baseline runs exist.
    """
    suffix_html = (
        f"<span class='metric-suffix'>{suffix}</span>" if suffix else ""
    )
    cell_htmls = "".join(
        f"<div class='metric-value'>{c}</div>" for c in cells
    )
    return (
        "<div class='metric-row canary-row'>"
        f"<div class='metric-label'>{label}{suffix_html}</div>"
        f"{cell_htmls}"
        "</div>"
    )


def _canary_section(title: str, rows_html: str) -> str:
    """Mirror of the Metrics tab `.section-block` container — header row
    carries the trajectory column labels (Benchmark | +1 | +2 | +3)."""
    plus_headers = "".join(
        f"<div class='col-header numeric'>+{i + 1}</div>"
        for i in range(CANARY_TRAJECTORY_SLOTS)
    )
    return (
        "<div class='section-block canary-section'>"
        f"<div class='section-title'>{title}</div>"
        "<div class='metric-row header canary-row'>"
        "<div class='col-header'>Metric</div>"
        "<div class='col-header numeric'>Benchmark</div>"
        f"{plus_headers}"
        "</div>"
        f"{rows_html}"
        "</div>"
    )


def _trajectory_cells(
    formatter,
    benchmark_value,
    post_run_values: list,
) -> list[str]:
    """Build the 4-cell trajectory series for one metric row.

    `formatter` receives a value (or None) and returns the formatted string
    for display. `benchmark_value` is the baseline-run value (em-dash when
    no baseline). `post_run_values` is a list of up to N values, in
    chronological order, padded with em-dash when fewer than N exist."""
    cells = [formatter(benchmark_value) if benchmark_value is not None else EM_DASH_CELL]
    for i in range(CANARY_TRAJECTORY_SLOTS):
        if i < len(post_run_values) and post_run_values[i] is not None:
            cells.append(formatter(post_run_values[i]))
        else:
            cells.append(EM_DASH_CELL)
    return cells


def format_canary_health_blocks(
    latest_run_records: list[InteractionRecord],
    baseline_records: list[InteractionRecord],
    all_records: list[InteractionRecord],
    corpus,
    flags: list[CanaryDriftFlag],
    post_baseline_runs: list[list[InteractionRecord]] | None = None,
) -> str:
    """Three health sections (Drift / Quality / Latency) — trajectory view.

    Each row renders 5 columns: Metric | Benchmark | +1 | +2 | +3, where +N
    is the Nth canary run that happened after the baseline was frozen.
    Empty slots (fewer than CANARY_TRAJECTORY_SLOTS post-baseline runs
    exist) render as em-dash placeholders. Pre-#51 the layout was
    (Current | Δ baseline) for the latest-run snapshot; the trajectory
    view shows the temporal arc instead.

    `post_baseline_runs` is a list of up to CANARY_TRAJECTORY_SLOTS record
    lists, one per +N run in chronological order. When None or empty
    (cold-start / freshly-frozen baseline) all +N columns render em-dash.

    Cold-start safe — when `baseline_records` is empty, every cell degrades
    to em-dash instead of crashing."""
    if not latest_run_records and not (post_baseline_runs or []):
        # Nothing to render even on a blank trajectory — no canary records on disk.
        return ""

    baseline_model = DashboardModel(
        baseline_records, include_canary=True, only_canary=True,
    ) if baseline_records else None

    post_baseline_runs = post_baseline_runs or []
    post_models = [
        DashboardModel(records, include_canary=True, only_canary=True)
        for records in post_baseline_runs
    ]

    def _benchmark(fn):
        return fn(baseline_model) if baseline_model is not None else None

    def _benchmark_with_corpus(fn):
        return fn(baseline_model, corpus) if baseline_model is not None else None

    def _post_values(fn) -> list:
        return [fn(m) for m in post_models]

    def _post_values_with_corpus(fn) -> list:
        return [fn(m, corpus) for m in post_models]

    # Plain-number formatter for drift counts (no scaling).
    def _fmt_int(v):
        return EM_DASH_CELL if v is None else str(v)

    # ---- Drift ------------------------------------------------------------
    # Drift counts compare each post-baseline run vs the baseline. The
    # benchmark column reads em-dash (drift against itself is structurally 0;
    # rendering that would be misleading).
    from collections import Counter

    def _drift_counts_for_run(run_records: list[InteractionRecord]) -> tuple[int, int, int]:
        """Returns (total, major, minor) drift flags for one post-baseline run."""
        if not run_records or not baseline_records:
            return (0, 0, 0)
        from canary_drift import detect_drift
        run_flags = detect_drift(run_records, baseline_records, corpus)
        sev = Counter(f.severity for f in run_flags)
        return (len(run_flags), sev.get("major", 0), sev.get("minor", 0))

    per_run_drift = [_drift_counts_for_run(r) for r in post_baseline_runs]
    total_drift_post = [t for t, _, _ in per_run_drift]
    major_drift_post = [m for _, m, _ in per_run_drift]
    minor_drift_post = [n for _, _, n in per_run_drift]

    drift_rows = (
        _canary_metric_row(
            "Total drift flags",
            _trajectory_cells(_fmt_int, None, total_drift_post),
        )
        + _canary_metric_row(
            "Major drift",
            _trajectory_cells(_fmt_int, None, major_drift_post),
        )
        + _canary_metric_row(
            "Minor drift",
            _trajectory_cells(_fmt_int, None, minor_drift_post),
        )
    )

    # ---- Quality ----------------------------------------------------------
    def _pass_rate(model: DashboardModel | None) -> float | None:
        if model is None or not model.records:
            return None
        return 1 - model.guardrail_rejection_rate

    quality_rows = (
        _canary_metric_row(
            "First-attempt pass rate",
            _trajectory_cells(_fmt_pct, _pass_rate(baseline_model), [_pass_rate(m) for m in post_models]),
        )
        + _canary_metric_row(
            "Outcome accuracy",
            _trajectory_cells(
                _fmt_pct,
                _benchmark_with_corpus(lambda m, c: m.outcome_accuracy(c)),
                _post_values_with_corpus(lambda m, c: m.outcome_accuracy(c)),
            ),
            suffix="vs expected_outcome",
        )
        + _canary_metric_row(
            "Keyword coverage",
            _trajectory_cells(
                _fmt_pct,
                _benchmark_with_corpus(lambda m, c: m.keyword_coverage(c)),
                _post_values_with_corpus(lambda m, c: m.keyword_coverage(c)),
            ),
            suffix="substantive answers",
        )
        + _canary_metric_row(
            "Red-flag rate",
            _trajectory_cells(
                _fmt_pct,
                _benchmark_with_corpus(lambda m, c: m.red_flag_rate(c)),
                _post_values_with_corpus(lambda m, c: m.red_flag_rate(c)),
            ),
            suffix="must_not_appear hits",
        )
        + _canary_metric_row(
            "Gap rate",
            _trajectory_cells(
                _fmt_pct,
                _benchmark(lambda m: m.gap_rate),
                _post_values(lambda m: m.gap_rate),
            ),
        )
        + _canary_metric_row(
            "Refusal rate",
            _trajectory_cells(
                _fmt_pct,
                _benchmark(lambda m: m.refusal_rate),
                _post_values(lambda m: m.refusal_rate),
            ),
        )
        + _canary_metric_row(
            "Mean classification confidence",
            _trajectory_cells(
                lambda v: _fmt_num(v, 3),
                _benchmark(lambda m: m.mean_classification_confidence),
                _post_values(lambda m: m.mean_classification_confidence),
            ),
        )
        + _canary_metric_row(
            "Tool call success rate",
            _trajectory_cells(
                _fmt_pct,
                _benchmark(lambda m: m.tool_call_success_rate),
                _post_values(lambda m: m.tool_call_success_rate),
            ),
        )
    )

    # ---- Latency ----------------------------------------------------------
    def _stage_p95(model: DashboardModel | None, stage: str) -> float | None:
        if model is None or not model.records:
            return None
        return model.latency_percentiles(stage).get(95)

    latency_stages = [
        ("Total p95", "total"),
        ("Classifier p95", "classifier"),
        ("Retrieval p95", "retrieval"),
        ("Generation p95", "generation"),
        ("Guardrail p95", "guardrail"),
    ]
    latency_rows = ""
    for label, stage in latency_stages:
        latency_rows += _canary_metric_row(
            label,
            _trajectory_cells(
                _fmt_seconds,
                _stage_p95(baseline_model, stage),
                [_stage_p95(m, stage) for m in post_models],
            ),
        )

    return (
        _canary_section("Drift", drift_rows)
        + _canary_section("Quality", quality_rows)
        + _canary_section("Latency", latency_rows)
    )


def format_canary_stratified(flags: list[CanaryDriftFlag], corpus) -> str:
    """Stratified summary chips: drift counts grouped three ways — by
    expected_outcome, by category, and by drift kind. Lets the operator scan
    'where is drift concentrated?' before scrolling cards. Renders an
    empty-state line when no drift fired."""
    if not flags:
        return (
            "<div class='canary-stratified-empty'>"
            "No drift this run."
            "</div>"
        )

    summary = stratified_summary(flags, corpus)
    by_outcome = summary["by_outcome"]
    by_category = summary["by_category"]
    by_kind = summary["by_drift_kind"]

    def _chips(items):
        return " · ".join(
            f"<span class='canary-chip'>{html.escape(str(k))} <strong>{v}</strong></span>"
            for k, v in sorted(items, key=lambda x: -x[1])
        ) or "—"

    return (
        "<div class='canary-stratified'>"
        f"<div><span class='canary-stratified-label'>By outcome:</span> {_chips(by_outcome.items())}</div>"
        f"<div><span class='canary-stratified-label'>By category:</span> {_chips(by_category.items())}</div>"
        f"<div><span class='canary-stratified-label'>By kind:</span> {_chips(by_kind.items())}</div>"
        "</div>"
    )


def format_canary_drift_card(flag: CanaryDriftFlag) -> str:
    """One drift-flag card. Mirrors `format_flag_card` styling but reads the
    `CanaryDriftFlag.severity` to pick neon-red (major) vs amber (minor)."""
    sev = "alert" if flag.severity == "major" else "warning"
    return (
        f"<div class='canary-drift-card sev-{sev}'>"
        f"<div class='canary-drift-headline'>{html.escape(flag.headline)}</div>"
        f"<div class='canary-drift-detail'>"
        f"<code>{html.escape(flag.question)}</code> · "
        f"{html.escape(flag.detail)}</div>"
        "</div>"
    )


def format_canary_per_question_table(
    flags: list[CanaryDriftFlag],
    corpus,
    *,
    show_all: bool = False,
) -> str:
    """Per-question drift rows. Defaults to drifting-only; ``show_all=True``
    renders every corpus question with a dim row when no drift fired."""
    drifting = {f.question for f in flags}
    flags_by_question: dict[str, list[CanaryDriftFlag]] = {}
    for f in flags:
        flags_by_question.setdefault(f.question, []).append(f)

    rows = []
    for q in corpus:
        if not show_all and q.question not in drifting:
            continue
        question_flags = flags_by_question.get(q.question, [])
        if question_flags:
            top_severity = "major" if any(
                f.severity == "major" for f in question_flags
            ) else "minor"
            kind_summary = ", ".join(sorted({f.kind for f in question_flags}))
        else:
            top_severity = "healthy"
            kind_summary = "—"
        rows.append(
            f"<tr class='canary-row sev-{top_severity}'>"
            f"<td><code>{html.escape(q.id)}</code></td>"
            f"<td>{html.escape(q.question)}</td>"
            f"<td>{html.escape(q.expected_outcome)}</td>"
            f"<td>{html.escape(kind_summary)}</td>"
            f"<td class='canary-sev'>{top_severity}</td>"
            "</tr>"
        )
    if not rows:
        msg = (
            "No canary questions drifted this run."
            if not show_all else "Empty corpus."
        )
        return f"<div class='canary-empty'>{msg}</div>"
    return (
        "<table class='canary-table'>"
        "<thead><tr>"
        "<th>ID</th><th>Question</th><th>Expected outcome</th>"
        "<th>Drift kinds</th><th>Severity</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _kb_coverage_entries(records: list[InteractionRecord]) -> list[CoverageEntry]:
    """Flatten retrieved chunks across `records` and cross-reference against
    the canonical KB section list. Pure helper — Sentinel calls this at
    page-load and refresh."""
    flat = [chunk for r in records for chunk in r.retrieved_chunks]
    return compute_coverage(flat, load_sections())


def _build_canary_drift_state(
    all_records: list[InteractionRecord],
    *,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
) -> tuple[
    list[CanaryDriftFlag],
    list[InteractionRecord],
    dict | None,
    list,
    list[list[InteractionRecord]],
]:
    """Resolve drift between the latest canary run and the frozen baseline.

    Returns ``(flags, latest_run_records, baseline_pointer, corpus,
    post_baseline_run_records)``. The fifth tuple element (added in #51) is
    a list of up to CANARY_TRAJECTORY_SLOTS record lists, one per +N run in
    chronological order — feeds the trajectory view in
    ``format_canary_health_blocks``. Each can be empty / None on cold
    start; the caller renders the appropriate placeholder."""
    try:
        corpus = load_canaries(corpus_path)
    except (FileNotFoundError, ValueError):
        corpus = []

    runs = _canary_runs_grouped(all_records)
    latest_records: list[InteractionRecord] = runs[-1][1] if runs else []

    pointer = read_baseline(baseline_path)
    canary_only = [r for r in all_records if r.is_canary]
    baseline_records = resolve_baseline_records(canary_only, baseline_path)

    # Post-baseline trajectory runs (Session 51 — +1 / +2 / +3).
    post_run_ids = runs_after_baseline(
        canary_only, n=CANARY_TRAJECTORY_SLOTS, path=baseline_path,
    )
    by_run: dict[str, list[InteractionRecord]] = {}
    for r in canary_only:
        if r.run_id in post_run_ids:
            by_run.setdefault(r.run_id, []).append(r)
    post_baseline_runs = [by_run.get(rid, []) for rid in post_run_ids]

    flags: list[CanaryDriftFlag] = []
    if latest_records and baseline_records and corpus:
        flags = detect_drift(latest_records, baseline_records, corpus)
    return flags, latest_records, pointer, corpus, post_baseline_runs


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
    "answered_with_substance_rate": "Answered with substance",
    "low_confidence_rate": "Low-confidence rate (<0.7)",
    "mean_classification_confidence": "Classifier mean confidence",
    "latency_p95_total": "Total latency p95",
    "technical_tool_call_rate": "Tool calls / TECHNICAL turn",
    "tool_call_success_rate": "Tool-call success rate",
    "contact_conversion_rate": "Contact-conversion rate",
    "contact_offer_rate": "Contact-offer rate",
    "turns_per_session_median": "Turns/session (median)",
    "mean_turns_per_session": "Avg questions per session",
}

THEMATIC_BLOCKS: dict[str, list[str]] = {
    "Outcome": [
        "answered_with_substance_rate", "gap_rate", "deflection_rate",
        "refusal_rate", "guardrail_rejection_rate", "retry_exhausted_rate",
    ],
    "Routing": ["mean_classification_confidence", "low_confidence_rate"],
    "Engagement": [
        "mean_turns_per_session", "turns_per_session_median",
        "contact_offer_rate", "contact_conversion_rate",
    ],
    "Tool use": ["technical_tool_call_rate", "tool_call_success_rate"],
    "Latency": ["latency_p95_total"],
}

# Per-branch palette — fixed dict-iteration order is the source of truth
# for both the bar-grouping order and the shared legend at the top of the
# Trends tab. Distinct from the failure-feed mode palette (which lives on
# the Failures tab); same hue family, different roles per tab.
BRANCH_CHART_COLORS: dict[str, str] = {
    "GENERIC":     "#60a5fa",  # blue
    "GAP":         "#9ca3af",  # gray (the "no answer" branch — neutral)
    "TECHNICAL":   "#34d399",  # green
    "BEHAVIOURAL": "#c084fc",  # purple
    "LOGISTICAL":  "#fb923c",  # orange
}
BRANCH_BAR_ALPHA = 0.85



# Per-metric unit registry for chart formatting / scaling. Independent of
# THRESHOLDS post-#48: Tier B metrics (gap_rate, deflection_rate, etc.) are
# no longer in THRESHOLDS but still need pp/ms unit info for their chart
# labels and value formatting. Tier A metrics also resolve here for
# consistency. Default fall-through is "" (raw number).
METRIC_UNITS: dict[str, str] = {
    # Rates (percentage points)
    "gap_rate": "pp",
    "deflection_rate": "pp",
    "refusal_rate": "pp",
    "guardrail_rejection_rate": "pp",
    "retry_exhausted_rate": "pp",
    "answered_with_substance_rate": "pp",
    "low_confidence_rate": "pp",
    "technical_tool_call_rate": "pp",
    "tool_call_success_rate": "pp",
    "contact_conversion_rate": "pp",
    "contact_offer_rate": "pp",
    # Latency (milliseconds)
    "latency_p95_total": "ms",
    # Raw numbers (no scale, no suffix)
    "mean_classification_confidence": "",
    "turns_per_session_median": "",
    "mean_turns_per_session": "",
}


def _unit_for(metric: str) -> str:
    """Resolve the metric's display unit. Falls back to THRESHOLDS for
    backward compatibility, then to "" (raw number)."""
    if metric in METRIC_UNITS:
        return METRIC_UNITS[metric]
    threshold = THRESHOLDS.get(metric)
    if threshold is not None:
        return threshold.unit
    return ""


def _y_axis_title(metric: str) -> str:
    label = METRIC_LABELS.get(metric, metric)
    unit = _unit_for(metric)
    if unit == "pp":
        return f"{label} (%)"
    if unit == "ms":
        return f"{label} (s)"
    return label


def _scale_value(metric: str, value: float | None) -> float | None:
    """Convert raw values to chart-axis units. ``pp`` → percentages (×100);
    ``ms`` → seconds (÷1000); other passes through."""
    if value is None:
        return None
    unit = _unit_for(metric)
    if unit == "pp":
        return value * 100
    if unit == "ms":
        return value / 1000
    return value


def _fmt_metric_value(metric: str, value: float | None) -> str:
    unit = _unit_for(metric)
    if unit == "pp":
        return _fmt_pct(value)
    if unit == "ms":
        return _fmt_seconds(value)
    return _fmt_num(value)


@dataclass(frozen=True)
class BarPoint:
    """One bar position in the grouped bar chart.

    `value` is in chart-axis units (post-`_scale_value`); `has_data=False`
    means the branch had no records (or the metric returned None) in the
    window — the bar renders at zero height with a `—` annotation rather
    than as a 0% bar, so `no data` is visually distinct from `measured 0%`.
    """
    window: str
    branch: str
    value: float
    has_data: bool


def bar_chart_data(model: DashboardModel, metric: str) -> list[BarPoint]:
    """Per-(window, branch) bar positions for the Trends bar chart.

    Iterates `WINDOWS` × `BRANCH_CHART_COLORS` in stable order; the caller
    can rely on the result tracking the visual layout of bar groups (left to
    right) and bar slots within each group (legend order).
    """
    points: list[BarPoint] = []
    for window_label, days in WINDOWS:
        window_model = model.for_window(days=days)
        for branch in BRANCH_CHART_COLORS:
            branch_records = [r for r in window_model.records if r.branch == branch]
            if not branch_records:
                points.append(BarPoint(window_label, branch, 0.0, False))
                continue
            value = METRIC_GETTERS[metric](DashboardModel(branch_records))
            if value is None:
                points.append(BarPoint(window_label, branch, 0.0, False))
            else:
                scaled = _scale_value(metric, value)
                points.append(BarPoint(window_label, branch, float(scaled), True))
    return points


def render_metric_bars(
    model: DashboardModel,
    metric: str,
    *,
    height: int = 220,
) -> Figure:
    """Grouped bar chart — N windows × M branches per window.

    X-axis: WINDOWS labels (7d / 30d / 90d / Global). Y-axis: metric value
    in chart-axis units. One coloured bar per branch within each window
    group; bars whose value is undefined render at zero with a `—`
    annotation so missing data is visually distinct from a measured zero.

    Threshold reference lines drawn as faint horizontal dashes at the
    healthy/warning levels for thresholded metrics. No legend on the figure
    itself — the shared `.branch-legend` strip at the top of the Trends tab
    carries the colour↔branch mapping for every chart on the page.

    Uses `matplotlib.figure.Figure` directly (not `plt.subplots`) so figures
    don't accumulate in the pyplot global registry across the many renders
    this dashboard does.
    """
    points = bar_chart_data(model, metric)

    # 10in × dpi=200 → 2000px wide; same canvas size as the line chart.
    fig = Figure(figsize=(10, height / 100), dpi=200, facecolor="#1c1c20")
    ax = fig.add_subplot(111)
    ax.set_facecolor("#1c1c20")

    n_windows = len(WINDOWS)
    n_branches = len(BRANCH_CHART_COLORS)
    # 0.78 group width leaves ~22% spacing between groups for visual breathing.
    bar_width = 0.78 / n_branches
    group_positions = list(range(n_windows))

    # Index points by (window, branch) for stable lookup per branch series.
    by_key = {(p.window, p.branch): p for p in points}
    em_dash_targets: list[tuple[float, float]] = []  # (x, y_baseline) for `—` labels

    for i, (branch, color) in enumerate(BRANCH_CHART_COLORS.items()):
        offset = (i - (n_branches - 1) / 2) * bar_width
        x_positions = [pos + offset for pos in group_positions]
        values = [by_key[(label, branch)].value for label, _ in WINDOWS]
        has_data = [by_key[(label, branch)].has_data for label, _ in WINDOWS]
        ax.bar(
            x_positions, values, bar_width,
            color=color, alpha=BRANCH_BAR_ALPHA, edgecolor="none", zorder=2,
        )
        for x, ok in zip(x_positions, has_data):
            if not ok:
                em_dash_targets.append((x, 0.0))

    # `—` annotations for missing-data positions — drawn after bars so the
    # text sits above the (zero-height) bar mark.
    for x, y in em_dash_targets:
        ax.text(
            x, y, "—", ha="center", va="bottom",
            color="#5a5a64", fontsize=7, zorder=3,
        )

    # X-axis: categorical window labels, no tick lines.
    ax.set_xticks(group_positions)
    ax.set_xticklabels(
        [label for label, _ in WINDOWS],
        color="#9999a3", fontsize=8.5,
    )
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", colors="#9999a3", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#1f1f24")
    ax.set_ylabel(_y_axis_title(metric), color="#9999a3", fontsize=9)
    ax.grid(True, axis="y", color="#1f1f24", linewidth=0.5, zorder=1)
    ax.set_axisbelow(True)

    # Y-axis floor at zero (rates) — without this matplotlib auto-frames the
    # zero-height "no data" bars off the bottom edge.
    ymin, ymax = ax.get_ylim()
    if ymin > 0:
        ax.set_ylim(0, ymax)

    fig.tight_layout()
    return fig


def branch_legend_html() -> str:
    """Shared per-branch colour swatches at the top of the Trends tab.

    One legend strip serves every chart below it — no per-chart legend
    chrome on individual figures. Iterates `BRANCH_CHART_COLORS` in fixed
    order so the swatch sequence matches the bar order within each group."""
    swatches = "".join(
        "<span class='branch-swatch'>"
        f"<span class='swatch-color' style='background:{color}'></span>"
        f"{branch}"
        "</span>"
        for branch, color in BRANCH_CHART_COLORS.items()
    )
    return (
        "<div class='branch-legend'>"
        "<span class='legend-label'>Branches</span>"
        f"{swatches}"
        "</div>"
    )


def format_trend_header(metric: str, model: DashboardModel) -> str:
    """Inline header above each chart — `<b>Label:</b> {global value}`.

    The chart itself is per-branch; the header surfaces the global aggregate
    as the headline number so the operator sees `what does this metric look
    like overall?` without summing the bars mentally. No status colour
    applied — Metrics tab is the source of truth for `is this healthy?`."""
    label = METRIC_LABELS.get(metric, metric)
    value = METRIC_GETTERS[metric](model)
    value_str = _fmt_metric_value(metric, value)
    return f"<b>{label}:</b> <span class='mono'>{value_str}</span>"


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


def _latest_canary_timestamp(records: list[InteractionRecord]) -> str | None:
    canary = [r for r in records if r.is_canary]
    if not canary:
        return None
    return max(r.timestamp for r in canary)


def ensure_fresh_canaries(
    reader: LogReader | None = None,
    *,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
    runner: callable = canary_runner.run_batch,
) -> str | None:
    """Run the canary batch when the most recent canary run is older than
    ``max_age_days`` (or absent). Sentinel calls this on launch alongside
    ``ensure_fresh_clusters`` / ``ensure_fresh_summaries`` per the issue
    spec; failures surface as a banner rather than crashing."""
    reader = reader or _default_reader()
    latest = _latest_canary_timestamp(reader.read())
    if latest is not None:
        latest_dt = datetime.fromisoformat(latest)
        if latest_dt > datetime.now(timezone.utc) - timedelta(days=max_age_days):
            return None
    return _run_with_capture("Canary", lambda: runner())


def _canary_runs_grouped(
    records: list[InteractionRecord],
) -> list[tuple[str, list[InteractionRecord]]]:
    """Group canary records by ``run_id``, ordered oldest-first by the run's
    earliest timestamp. Sparklines + per-run drift comparisons consume this
    chronologically."""
    canary = [r for r in records if r.is_canary and r.run_id]
    by_run: dict[str, list[InteractionRecord]] = {}
    for r in canary:
        by_run.setdefault(r.run_id, []).append(r)
    return sorted(
        by_run.items(),
        key=lambda kv: min(r.timestamp for r in kv[1]),
    )


def canary_metric_history(
    records: list[InteractionRecord],
    metric: str,
    *,
    last_n: int = CANARY_SPARK_WINDOW,
) -> list[float | None]:
    """One value per canary run for ``metric``, oldest-first, capped to the
    last ``last_n`` runs. Powers the inline sparkline column on the canary
    health blocks."""
    getter = METRIC_GETTERS.get(metric)
    if getter is None:
        return []
    runs = _canary_runs_grouped(records)[-last_n:]
    return [
        getter(DashboardModel(rs, include_canary=True, only_canary=True))
        for _, rs in runs
    ]


def render_sparkline(
    values: list[float | None],
    baseline: float | None,
) -> Figure | None:
    """Tiny matplotlib sparkline: line over ``values`` with a horizontal
    reference line at ``baseline``. Returns ``None`` when there's nothing
    to draw (≤ 1 valid value) so the caller can render a `—` placeholder."""
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return None
    fig = Figure(figsize=(1.6, 0.32), dpi=150)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("#1c1c20")  # bg-surface-2
    ax.set_facecolor("#1c1c20")
    xs = list(range(len(values)))
    ys = [v if v is not None else float("nan") for v in values]
    ax.plot(xs, ys, color="#9ca3af", linewidth=1.0)
    if baseline is not None:
        ax.axhline(baseline, color="#5a5a64", linewidth=0.6,
                   linestyle="--", alpha=0.9)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig


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
                gr.Markdown("<div class='section-header-major'>Flags</div>")
                # Empty-state markdown shows when no flags fire.
                initial_flags = _build_flags(model)
                flags_empty_md = gr.Markdown(
                    "" if initial_flags else FLAGS_EMPTY_PLACEHOLDER
                )
                # Pre-allocated per-flag slots: each slot is a single
                # full-width gr.Button styled as a card. Clicking anywhere
                # on the card switches to the target tab. Slots beyond the
                # active flag count render hidden.
                flag_btns: list[gr.Button] = []
                for i in range(MAX_FLAGS_RENDERED):
                    if i < len(initial_flags):
                        f = initial_flags[i]
                        btn_value = f"{f.headline}\n{f.detail}"
                        slot_visible = True
                    else:
                        btn_value = ""
                        slot_visible = False
                    flag_btns.append(
                        gr.Button(
                            btn_value, visible=slot_visible,
                            elem_classes=["flag-button"],
                        )
                    )
                # Per-slot target tab state — read by the click handlers to
                # know where to jump.
                flag_target_state = gr.State(
                    [
                        FLAG_TARGET_TAB.get(initial_flags[i].target, TAB_METRICS)
                        if i < len(initial_flags) else ""
                        for i in range(MAX_FLAGS_RENDERED)
                    ]
                )

                gr.Markdown("<div class='section-header-major'>Health overview</div>")
                metrics_md = gr.Markdown(
                    format_metrics_overview(models, priors, DISPLAY_MODE_DEFAULT)
                )

                with gr.Accordion("Glossary", open=False):
                    gr.Markdown(format_metrics_glossary())

            # ---- Trends tab -----------------------------------------------
            with gr.Tab("Trends", id=TAB_TRENDS):
                gr.Markdown("<div class='section-header-major'>Trend Explorer</div>")

                # Shared per-branch legend at the top — one strip serves
                # every chart on the page (no per-chart legend chrome).
                gr.Markdown(branch_legend_html())

                bar_charts: dict[str, gr.Plot] = {}
                bar_headers: dict[str, gr.Markdown] = {}
                # Global 2-per-row cap (Session 53). Pre-#53 only Outcome was
                # capped at 2; the others jammed every chart onto one row,
                # which collapsed the per-chart axis space on Engagement (4
                # metrics post-#48). One rule for all blocks now: at most 2
                # charts per row, every block. Singletons (Latency =
                # latency_p95_total) render as a half-width chart.
                CHARTS_PER_ROW = 2
                for block_name, block_metrics in THEMATIC_BLOCKS.items():
                    gr.Markdown(
                        f"<div class='section-header'>{block_name}</div>"
                    )
                    for chunk_start in range(0, len(block_metrics), CHARTS_PER_ROW):
                        chunk = block_metrics[chunk_start:chunk_start + CHARTS_PER_ROW]
                        with gr.Row():
                            for metric in chunk:
                                with gr.Column(min_width=320, elem_classes=["chart-card"]):
                                    bar_headers[metric] = gr.Markdown(
                                        f"<div class='chart-header'>{format_trend_header(metric, model)}</div>"
                                    )
                                    bar_charts[metric] = gr.Plot(
                                        value=render_metric_bars(model, metric),
                                        show_label=False,
                                    )

            # ---- Canary tab -----------------------------------------------
            # Drift-focused panel: per-question regression detection against
            # a frozen golden baseline. Sentinel never auto-runs the canary
            # batch — operator triggers it via `uv run python src/canary_runner.py`.
            with gr.Tab("Canary", id=TAB_CANARY):
                gr.Markdown("<div class='section-header-major'>Canary drift</div>")
                (
                    initial_drift_flags,
                    initial_latest_run,
                    initial_pointer,
                    canary_corpus,
                    initial_post_baseline_runs,
                ) = _build_canary_drift_state(reader.read())

                canary_banner_md = gr.Markdown(format_canary_drift_summary(
                    initial_pointer, initial_latest_run, initial_drift_flags
                ))
                # Three thematic health blocks per the issue #39 spec —
                # Drift / Quality / Latency, post-#51 each renders a 5-column
                # trajectory: Metric | Benchmark | +1 | +2 | +3 (the 3
                # canary runs that came after the frozen baseline). Sits
                # immediately under the banner so the operator reads health
                # before scrolling.
                initial_baseline_records = resolve_baseline_records(
                    [r for r in reader.read() if r.is_canary],
                ) if initial_pointer is not None else []
                initial_all_records = reader.read()
                canary_blocks_md = gr.Markdown(format_canary_health_blocks(
                    initial_latest_run, initial_baseline_records,
                    initial_all_records, canary_corpus, initial_drift_flags,
                    post_baseline_runs=initial_post_baseline_runs,
                ))
                # Stratified summary chips — drift counts grouped by branch,
                # category, and kind. Different signal from the blocks (which
                # are absolute health): chips answer "where is drift
                # concentrated?", blocks answer "what's the metric value?"
                canary_stratified_md = gr.Markdown(format_canary_stratified(
                    initial_drift_flags, canary_corpus,
                ))
                canary_drift_md = gr.Markdown(
                    "\n".join(format_canary_drift_card(f) for f in initial_drift_flags)
                    if initial_drift_flags
                    else ""
                )

                gr.Markdown("<div class='section-header'>Per-question</div>")
                with gr.Row():
                    canary_show_all = gr.Checkbox(
                        value=False, label="Show all (not just drifting)"
                    )
                canary_table_md = gr.Markdown(format_canary_per_question_table(
                    initial_drift_flags, canary_corpus, show_all=False,
                ))

                # Re-baseline tucked inside a collapsed accordion so accidental
                # clicks need two deliberate actions (expand + click). Overwriting
                # the frozen golden reference is silent and irreversible without
                # a backup, so the friction is load-bearing — see LIMITATIONS::P12.
                with gr.Accordion(
                    "Advanced — re-baseline (overwrites the frozen reference)",
                    open=False,
                ):
                    gr.Markdown(
                        "<div class='canary-rebaseline-warning'>"
                        "Promotes the <strong>latest canary run</strong> to the "
                        "new frozen golden baseline. All future drift comparisons "
                        "will run against this run.<br><br>"
                        "<strong>Use this only after intentional changes</strong> "
                        "(KB rewrite, prompt tightening, model upgrade) where you've "
                        "reviewed the drift and accept the new behaviour as correct. "
                        "Clicking this on an unintentional regression silently locks "
                        "in the bug — see <code>LIMITATIONS::P12</code>."
                        "</div>"
                    )
                    with gr.Row():
                        gr.Markdown("")  # left spacer pushes button right
                        rebaseline_btn = gr.Button(
                            "Re-baseline",
                            variant="secondary",
                            size="sm",
                            scale=0,
                        )
                    rebaseline_status_md = gr.Markdown("")

            # ---- Failures tab ---------------------------------------------
            with gr.Tab("Failures", id=TAB_FAILURES):
                gr.Markdown(
                    "<div class='section-header-major'>Failure Feed</div>"
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

                gr.Markdown("<div class='section-header-major'>Gap Clusters</div>")
                cluster_md = gr.Markdown(
                    format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH))
                )

                gr.Markdown("<div class='section-header-major'>Deflection summary</div>")
                deflection_md = gr.Markdown(
                    format_deflection_panel(read_summary("deflection", DEFAULT_SUMMARIES_DIR))
                )

            # KB Source Coverage lives on its own tab (post-Session 50). Pre-#50
            # it was a section under Failures; the move surfaces it as a
            # first-class operator surface for KB-coverage health rather than
            # a sub-section read after the failure drilldown.
            with gr.Tab("KB Coverage", id=TAB_KB_COVERAGE):
                gr.Markdown("<div class='section-header-major'>KB Source Coverage</div>")
                kb_coverage_md = gr.Markdown(
                    format_kb_coverage_panel(_kb_coverage_entries(model.records))
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

            # Per-flag slot updates: row visible only when its slot has a
            # flag; card markdown holds the card HTML; link button shows
            # Per-flag slot updates: each slot's button carries the
            # multi-line label (headline + detail) and the matching tab id is
            # queued in flag_target_state for the click handler to read.
            btn_updates: list = []
            target_state: list[str] = []
            for i in range(MAX_FLAGS_RENDERED):
                if i < len(flags):
                    f = flags[i]
                    btn_updates.append(gr.update(
                        visible=True,
                        value=f"{f.headline}\n{f.detail}",
                    ))
                    target_state.append(FLAG_TARGET_TAB.get(f.target, TAB_METRICS))
                else:
                    btn_updates.append(gr.update(visible=False, value=""))
                    target_state.append("")

            flags_empty_html = "" if flags else FLAGS_EMPTY_PLACEHOLDER

            # Canary panel re-render — re-resolves drift state against the
            # latest run + frozen baseline. No batch trigger here: canary
            # runs are operator-driven via the CLI, not auto-refreshed.
            all_records = reader.read()
            (
                drift_flags, latest_run_recs, baseline_pointer, corpus,
                post_baseline_run_recs,
            ) = _build_canary_drift_state(all_records)
            canary_banner_html = format_canary_drift_summary(
                baseline_pointer, latest_run_recs, drift_flags,
            )
            canary_baseline_recs = (
                resolve_baseline_records([r for r in all_records if r.is_canary])
                if baseline_pointer is not None else []
            )
            canary_blocks_html = format_canary_health_blocks(
                latest_run_recs, canary_baseline_recs,
                all_records, corpus, drift_flags,
                post_baseline_runs=post_baseline_run_recs,
            )
            canary_stratified_html = format_canary_stratified(drift_flags, corpus)
            canary_drift_html = (
                "\n".join(format_canary_drift_card(f) for f in drift_flags)
                if drift_flags else ""
            )
            canary_table_html = format_canary_per_question_table(
                drift_flags, corpus, show_all=False,
            )

            return [
                f"<div class='page-meta'>{format_header(source, new_loaded_at)}</div>",
                _autorefresh_banner([cluster_msg, summary_msg]),
                format_status_banner(_status_summary(headline)),
                flags_empty_html,
                *btn_updates,
                target_state,
                format_metrics_overview(new_models, new_priors, DISPLAY_MODE_DEFAULT),
                feed_summary_html,
                empty_html,
                *acc_updates,
                *body_updates,
                *state_values,
                format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH)),
                format_deflection_panel(read_summary("deflection", DEFAULT_SUMMARIES_DIR)),
                format_kb_coverage_panel(_kb_coverage_entries(new_model.records)),
                canary_banner_html,
                canary_blocks_html,
                canary_stratified_html,
                canary_drift_html,
                canary_table_html,
                # Trends — re-render every chart and its header. Aligned with
                # `bar_headers` + `bar_charts` dicts which iterate THEMATIC_BLOCKS
                # in the same order as the build-time pass below.
                *[
                    f"<div class='chart-header'>{format_trend_header(metric, new_model)}</div>"
                    for metrics in THEMATIC_BLOCKS.values() for metric in metrics
                ],
                *[
                    render_metric_bars(new_model, metric)
                    for metrics in THEMATIC_BLOCKS.values() for metric in metrics
                ],
            ]

        refresh_btn.click(
            fn=_refresh,
            inputs=[branch_dd, mode_dd, window_dd, search_in],
            outputs=[
                header_md, banner_md, status_md,
                flags_empty_md,
                *flag_btns,
                flag_target_state,
                metrics_md,
                feed_summary_md,
                feed_empty_md,
                *feed_accordions,
                *feed_drilldowns,
                *feed_session_states,
                cluster_md, deflection_md, kb_coverage_md,
                canary_banner_md,
                canary_blocks_md,
                canary_stratified_md,
                canary_drift_md,
                canary_table_md,
                *[bar_headers[m] for ms in THEMATIC_BLOCKS.values() for m in ms],
                *[bar_charts[m] for ms in THEMATIC_BLOCKS.values() for m in ms],
            ],
        )

        # Canary "show all" toggle — re-renders the per-question table with
        # the toggle's value passed through. Defaults to drifting-only.
        def _refresh_canary_table(show_all):
            (drift_flags, _latest, _ptr, corpus, _post) = _build_canary_drift_state(
                reader.read()
            )
            return format_canary_per_question_table(
                drift_flags, corpus, show_all=bool(show_all),
            )

        canary_show_all.change(
            fn=_refresh_canary_table,
            inputs=[canary_show_all],
            outputs=[canary_table_md],
        )

        # Re-baseline button — promote the latest canary run to the frozen
        # golden baseline. No-op (with a status message) when there's no
        # canary run to promote.
        def _rebaseline():
            from canary_baseline import freeze_baseline
            from pipeline import GIT_SHA
            runs = _canary_runs_grouped(reader.read())
            if not runs:
                return "<div class='canary-empty'>No canary run to promote.</div>"
            run_id = runs[-1][0]
            freeze_baseline(run_id, frozen_git_sha=GIT_SHA)
            return (
                f"<div class='canary-banner'>"
                f"Frozen baseline → run <code>{html.escape(run_id)}</code>."
                "</div>"
            )

        rebaseline_btn.click(
            fn=_rebaseline,
            outputs=[rebaseline_status_md],
        )

        # Per-flag click → switch to the target tab. The whole card-shaped
        # button is the click target; each button reads flag_target_state at
        # its slot index to know which tab to jump to.
        def _make_flag_click(slot_index: int):
            def _handler(targets):
                target = targets[slot_index] if slot_index < len(targets) else ""
                if not target:
                    return gr.update()
                return gr.Tabs(selected=target)
            return _handler

        for i, btn in enumerate(flag_btns):
            btn.click(
                fn=_make_flag_click(i),
                inputs=[flag_target_state],
                outputs=[tabs],
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

    return app


if __name__ == "__main__":
    build_app().launch(inbrowser=True)

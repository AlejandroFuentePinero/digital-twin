"""Local Gradio dashboard over the canonical interaction log (Phase 4 / issue #29).

Boots against `LogReader` (defaults to `LocalReader` over the JSONL backend; HF
Dataset is Phase 6). Manual refresh only — no auto-poll. Run locally with:

    uv run python src/sentinel.py
"""

from __future__ import annotations

import html
import os
from datetime import datetime, timezone

import gradio as gr
import pandas as pd

from branches import REGISTRY as BRANCH_REGISTRY
from cluster_gaps import DEFAULT_OUT_PATH as CLUSTERS_DEFAULT_PATH, read_clusters
from dashboard_model import METRIC_GETTERS, DashboardModel
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
from replayer import ReplayResult, replay

WINDOWS = [("Global", None), ("30d", 30), ("7d", 7)]

# Branch dropdown choices in Failure Feed; "All" prefixes the canonical branch list.
BRANCH_CHOICES = ["All", *BRANCH_REGISTRY.keys()]
FAILURE_MODE_CHOICES = ["All", *FAILURE_MODES]
FEED_TABLE_HEADERS = ["timestamp", "branch", "failure mode", "question", "attempts", "confidence"]


SENTINEL_CSS = """
.status-pill {
    display: inline-block;
    font-size: 0.72em; font-weight: 700; letter-spacing: 0.05em;
    padding: 2px 7px; border-radius: 4px;
    margin: 0 4px;
    text-transform: uppercase;
}
.status-pill.healthy { background: rgba(74, 222, 128, 0.14); color: #4ade80; }
.status-pill.warning { background: rgba(251, 146, 60, 0.16); color: #fb923c; }
.status-pill.alert   { background: rgba(248, 113, 113, 0.16); color: #f87171; }

.wow-delta {
    display: inline-block;
    font-size: 0.78em;
    margin-left: 4px;
    color: #94a3b8;
}
.wow-delta.improving { color: #4ade80; }
.wow-delta.degrading { color: #f87171; }
.wow-delta.stable    { color: #94a3b8; }
"""


def _default_reader() -> LogReader:
    if os.environ.get("HF_WRITE_TOKEN"):
        return HFReader()
    return LocalReader()


def _source_label(reader: LogReader) -> str:
    return "HF Dataset" if isinstance(reader, HFReader) else "Local JSONL"


def format_header(source: str, loaded_at: datetime) -> str:
    when = loaded_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"**Source:** {source}  ·  **Last loaded:** {when}"


EM_DASH = "—"


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


def _badge(metric_name: str | None, value: float | None) -> str:
    """Inline status pill HTML, or empty string when no threshold applies."""
    if metric_name is None:
        return ""
    status = metric_status(metric_name, value)
    if status is None:
        return ""
    return f'<span class="status-pill {status}">{status}</span>'


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
    """Render one metric row: ``- **label:** value badge delta``.

    `metric_name` of None means orientation/volume signal — no badge, no delta.
    `prior_value` of None means no WoW (e.g. Global window).
    """
    badge = _badge(metric_name, raw_value)
    delta = _delta(metric_name, raw_value, prior_value)
    return f"- **{label}:** {value_str}{badge}{delta}"


def format_panel(
    label: str,
    model: DashboardModel,
    prior_model: DashboardModel | None = None,
) -> str:
    """Render a full panel for ``label`` window. Pass ``prior_model`` to enable WoW deltas.

    Per issue #36: badges appear for thresholded metrics; orientation signals (volume,
    distribution, multi-label) render bare. Deltas appear only when a prior is provided.
    """

    def _prior(getter):
        return getter(prior_model) if prior_model is not None else None

    # Outcome ----------------------------------------------------------------
    outcome_rows = [
        _row("Total interactions", str(model.total_interactions)),  # volume
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

    # Routing ----------------------------------------------------------------
    routing_rows = [
        _row("Branch distribution", _fmt_branches(model.branch_distribution)),  # orientation
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
        _row("Multi-label rate", _fmt_pct(model.multi_label_rate)),  # orientation
    ]

    # Engagement -------------------------------------------------------------
    engagement_rows = [
        _row("Unique sessions", str(model.unique_sessions)),  # volume
        _row(
            "Turns/session (median)", _fmt_num(model.turns_per_session_median),
            metric_name="turns_per_session_median", raw_value=model.turns_per_session_median,
            prior_value=_prior(lambda m: m.turns_per_session_median),
        ),
        _row("Drop-off by turn", _fmt_dropoff(model.dropoff_by_turn)),  # orientation
        _row("Contact-offer rate", _fmt_pct(model.contact_offer_rate)),  # orientation
        _row(
            "Contact-conversion rate", _fmt_pct(model.contact_conversion_rate),
            metric_name="contact_conversion_rate", raw_value=model.contact_conversion_rate,
            prior_value=_prior(lambda m: m.contact_conversion_rate),
        ),
    ]

    # Tool use ---------------------------------------------------------------
    tool_rows = [
        _row(
            "Tool uptake (TECHNICAL)", _fmt_pct(model.technical_tool_uptake_rate),
            metric_name="technical_tool_uptake_rate", raw_value=model.technical_tool_uptake_rate,
            prior_value=_prior(lambda m: m.technical_tool_uptake_rate),
        ),
        _row("Tool-call success rate", _fmt_pct(model.tool_call_success_rate)),  # orientation
    ]

    # Latency ----------------------------------------------------------------
    total_p95 = model.latency_percentiles("total").get(95)
    total_p95_prior = _prior(lambda m: m.latency_percentiles("total").get(95))
    latency_rows = [
        _row("classifier", _fmt_latency_row(model.latency_percentiles("classifier"))),
        _row("retrieval", _fmt_latency_row(model.latency_percentiles("retrieval"))),
        _row("generation", _fmt_latency_row(model.latency_percentiles("generation"))),
        _row("guardrail", _fmt_latency_row(model.latency_percentiles("guardrail"))),
        _row(
            "total", _fmt_latency_row(model.latency_percentiles("total")),
            metric_name="latency_p95_total", raw_value=total_p95, prior_value=total_p95_prior,
        ),
    ]

    return (
        f"### {label}\n\n"
        f"**Outcome**\n\n" + "\n".join(outcome_rows) + "\n\n"
        f"**Routing**\n\n" + "\n".join(routing_rows) + "\n\n"
        f"**Engagement**\n\n" + "\n".join(engagement_rows) + "\n\n"
        f"**Tool use**\n\n" + "\n".join(tool_rows) + "\n\n"
        f"**Latency** (per stage)\n\n" + "\n".join(latency_rows) + "\n"
    )


# ---- Failure Feed (issue #31) -----------------------------------------------


def _failure_table_rows(rows: list[FailureRow]) -> list[list]:
    """Convert FailureRow list to gr.Dataframe-friendly 2D list (one row per failure)."""
    return [
        [
            row.timestamp,
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
        f"**Timestamp:** {record.timestamp}",
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
    """Per-session view: header (id, turn count, contact state, total latency) + one
    `<details>` collapsible per turn whose body is the per-turn drilldown."""
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


# ---- Cluster panel (issue #32) ----------------------------------------------


CLUSTER_EMPTY_PLACEHOLDER = (
    "_No cached gap clusters yet. Run `uv run python src/cluster_gaps.py` to "
    "generate `data/logs/gap_clusters.json`._"
)


def format_cluster_panel(data: dict | None) -> str:
    """Render the Cluster panel from a `gap_clusters.json` dict.

    `None` (file absent) renders a placeholder pointing at the batch script;
    a populated dict renders one entry per cluster with label · count · the
    sample questions verbatim.
    """
    if data is None:
        return CLUSTER_EMPTY_PLACEHOLDER
    clusters = data.get("clusters", [])
    if not clusters:
        return (
            f"_No clusters in the last {data.get('period_days', '?')} days "
            "(no gap turns, or all groups below the minimum size)._"
        )
    parts = [
        f"_Generated {data.get('generated_at', '?')} · window {data.get('period_days', '?')}d_",
        "",
    ]
    for cluster in clusters:
        parts.append(f"- **{cluster['label']}** · count {cluster['count']}")
        for example in cluster.get("examples", []):
            parts.append(f"    - {example}")
    return "\n".join(parts)


# ---- Replay-from-record (issue #38) -----------------------------------------


def _gap_status(record: InteractionRecord) -> str:
    """Human label for the record's gap-phrase outcome — drives the diff hint."""
    return "knew answer" if record.knew_answer else "hit gap phrase"


def _replay_side(label: str, record: InteractionRecord) -> str:
    """Render one side of the side-by-side comparison."""
    last_attempt = record.attempts[-1] if record.attempts else {"answer": "", "guardrail_feedback": ""}
    return (
        f"#### {label}\n"
        f"**Branch:** `{record.branch}`  ·  **Confidence:** {record.classification_confidence:.2f}  "
        f"·  **Status:** {_gap_status(record)}\n\n"
        f"**Answer:**\n\n{last_attempt.get('answer', '')}\n\n"
        f"**Guardrail feedback:**\n\n{last_attempt.get('guardrail_feedback', '')}"
    )


def format_replay_comparison(result: ReplayResult) -> str:
    """Side-by-side markdown of original vs current-pipeline records with diff hints
    (branch ✓/⚠, confidence delta, gap-phrase status delta) at the top."""
    original, current = result.original, result.current
    branch_marker = "✓" if original.branch == current.branch else "⚠"
    branch_diff = (
        f"`{original.branch}` → `{current.branch}` {branch_marker}"
    )
    conf_delta = current.classification_confidence - original.classification_confidence
    sign = "+" if conf_delta >= 0 else ""
    conf_diff = (
        f"{original.classification_confidence:.2f} → {current.classification_confidence:.2f} "
        f"({sign}{conf_delta:.2f})"
    )
    status_marker = "✓" if original.knew_answer == current.knew_answer else "⚠"
    status_diff = f"{_gap_status(original)} → {_gap_status(current)} {status_marker}"

    return (
        "### Replay against current pipeline\n\n"
        f"- **Branch:** {branch_diff}\n"
        f"- **Confidence:** {conf_diff}\n"
        f"- **Gap-phrase status:** {status_diff}\n\n"
        f"{_replay_side('Original', original)}\n\n"
        "---\n\n"
        f"{_replay_side('Current pipeline', current)}\n"
    )


# ---- Trend Explorer (issue #30) ---------------------------------------------

# Display labels for each plottable metric (mirrors format_panel's row labels). Single
# source of truth so scan-mode headers and investigate-mode chart titles stay in sync.
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

# 5 thematic blocks mirroring Panel 1's organisation. Every plottable metric appears
# in exactly one block. Adding a metric to METRIC_GETTERS without adding it here
# trips test_thematic_blocks_partition_every_plottable_metric_exactly_once.
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

# Investigate-mode window choices. days=None ("All-time") spans the data's date range.
TREND_WINDOWS: list[tuple[str, int | None]] = [
    ("7d", 7), ("30d", 30), ("90d", 90), ("All-time", None),
]


def _fmt_metric_value(metric: str, value: float | None) -> str:
    """Format a metric value per its threshold-table unit (pp / ms / decimal)."""
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

    Columns: ``date`` (date), ``value`` (float), ``series`` (str). Series values:
    ``"value"`` for the metric, ``"healthy"`` / ``"warning"`` for horizontal threshold
    references, ``"prior"`` when ``prior_model`` is supplied (the prior period shifted
    forward by ``days`` so it overlays the current window).

    Empty model → empty DataFrame (chart layer renders 'insufficient data' placeholder).
    """
    series = model.time_series_by_day(metric, days=days)
    if not series:
        return pd.DataFrame(columns=["date", "value", "series"])
    rows: list[dict] = [
        {"date": d, "value": v, "series": "value"}
        for d, v in series if v is not None
    ]
    threshold = THRESHOLDS.get(metric)
    if threshold is not None:
        first_date = series[0][0]
        last_date = series[-1][0]
        rows.extend([
            {"date": first_date, "value": threshold.healthy, "series": "healthy"},
            {"date": last_date, "value": threshold.healthy, "series": "healthy"},
            {"date": first_date, "value": threshold.warning, "series": "warning"},
            {"date": last_date, "value": threshold.warning, "series": "warning"},
        ])
    if prior_model is not None and days is not None:
        from datetime import timedelta as _td
        prior_series = prior_model.time_series_by_day(metric, days=days)
        for d, v in prior_series:
            if v is None:
                continue
            # Shift prior dates forward by `days` so they overlay the current window.
            rows.append({"date": d + _td(days=days), "value": v, "series": "prior"})
    return pd.DataFrame(rows)


def format_trend_header(
    metric: str,
    model: DashboardModel,
    prior_model: DashboardModel | None = None,
) -> str:
    """Inline markdown header above each mini chart: label · value · badge · WoW arrow."""
    label = METRIC_LABELS.get(metric, metric)
    value = METRIC_GETTERS[metric](model)
    value_str = _fmt_metric_value(metric, value)
    badge = _badge(metric, value)
    prior_value = METRIC_GETTERS[metric](prior_model) if prior_model is not None else None
    delta = _delta(metric, value, prior_value)
    return f"**{label}:** {value_str} {badge}{delta}"


def _load(reader: LogReader) -> tuple[DashboardModel, datetime]:
    return DashboardModel(reader.read()), datetime.now(timezone.utc)


def _render_panels(model: DashboardModel) -> list[str]:
    """Render one panel per window, attaching the matching prior-window model
    for WoW deltas (None for Global)."""
    return [
        format_panel(label, model.for_window(days=days), prior_model=model.for_prior_window(days=days))
        for label, days in WINDOWS
    ]


def _filter_records(reader: LogReader, window_label: str) -> list[InteractionRecord]:
    """Read all records and apply the window filter via DashboardModel.for_window."""
    days = dict(WINDOWS).get(window_label)
    return DashboardModel(reader.read()).for_window(days=days).records


def build_app(reader: LogReader | None = None) -> gr.Blocks:
    reader = reader or _default_reader()
    source = _source_label(reader)
    model, loaded_at = _load(reader)

    initial_failures = select_failures(model.records)

    with gr.Blocks(title="Digital Twin · Sentinel", css=SENTINEL_CSS) as app:
        with gr.Row():
            gr.Markdown("# Digital Twin · Sentinel")
            refresh_btn = gr.Button("↻ Refresh", variant="secondary", size="sm", scale=0)
        header_md = gr.Markdown(format_header(source, loaded_at))

        with gr.Row():
            panels: list[gr.Markdown] = []
            for panel_md in _render_panels(model):
                with gr.Column():
                    panels.append(gr.Markdown(panel_md))

        gr.Markdown("---\n## Failure Feed")

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
        selected_record = gr.State(None)

        with gr.Column(visible=True) as feed_view:
            failures_df = gr.Dataframe(
                headers=FEED_TABLE_HEADERS,
                value=_failure_table_rows(initial_failures),
                interactive=False,
                wrap=True,
            )
            drilldown_md = gr.Markdown("_Select a row above to see the per-turn drilldown._")
            with gr.Row():
                view_session_btn = gr.Button("View full session", interactive=False)
                replay_btn = gr.Button(
                    "▶ Replay against current pipeline",
                    interactive=False, variant="primary",
                )
            replay_md = gr.Markdown("")

        with gr.Column(visible=False) as session_view:
            session_md = gr.Markdown("")
            back_btn = gr.Button("← Back to feed")

        # Refresh button — reload disk + re-render Health Overview + re-render Feed under
        # the active filter set so a manual refresh updates everything coherently.
        def _refresh(branch, mode, window_label, search):
            new_model, new_loaded_at = _load(reader)
            records = new_model.for_window(days=dict(WINDOWS).get(window_label)).records
            rows = select_failures(
                records, branch=branch, failure_mode=mode, question_search=search
            )
            return [
                format_header(source, new_loaded_at),
                *_render_panels(new_model),
                _failure_table_rows(rows),
                rows,
                "_Select a row above to see the per-turn drilldown._",
                None, None,
                gr.update(interactive=False), gr.update(interactive=False),
                "",
            ]

        refresh_btn.click(
            fn=_refresh,
            inputs=[branch_dd, mode_dd, window_dd, search_in],
            outputs=[
                header_md, *panels,
                failures_df, rows_state, drilldown_md,
                selected_session_id, selected_record,
                view_session_btn, replay_btn, replay_md,
            ],
        )

        # Filter changes only refresh the failure feed (Panel 1 doesn't move with feed filters).
        def _refresh_feed(branch, mode, window_label, search):
            records = _filter_records(reader, window_label)
            rows = select_failures(
                records, branch=branch, failure_mode=mode, question_search=search
            )
            return (
                _failure_table_rows(rows),
                rows,
                "_Select a row above to see the per-turn drilldown._",
                None, None,
                gr.update(interactive=False), gr.update(interactive=False),
                "",
            )

        for control in (branch_dd, mode_dd, window_dd, search_in):
            control.change(
                fn=_refresh_feed,
                inputs=[branch_dd, mode_dd, window_dd, search_in],
                outputs=[
                    failures_df, rows_state, drilldown_md,
                    selected_session_id, selected_record,
                    view_session_btn, replay_btn, replay_md,
                ],
            )

        # Row click → drilldown + remember session_id and record for downstream actions.
        def _on_row_select(rows: list[FailureRow], evt: gr.SelectData):
            if not rows or evt.index is None:
                return (
                    "", None, None,
                    gr.update(interactive=False), gr.update(interactive=False),
                    "",
                )
            row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
            if row_idx >= len(rows):
                return (
                    "", None, None,
                    gr.update(interactive=False), gr.update(interactive=False),
                    "",
                )
            row = rows[row_idx]
            return (
                format_failure_drilldown(row.record),
                row.record.session_id,
                row.record,
                gr.update(interactive=True), gr.update(interactive=True),
                "",
            )

        failures_df.select(
            fn=_on_row_select,
            inputs=[rows_state],
            outputs=[
                drilldown_md, selected_session_id, selected_record,
                view_session_btn, replay_btn, replay_md,
            ],
        )

        # "View full session" → swap visible columns + render full session.
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

        # Back button → reverse the swap.
        def _back_to_feed():
            return gr.update(visible=True), gr.update(visible=False)

        back_btn.click(fn=_back_to_feed, outputs=[feed_view, session_view])

        # Replay button — two-stage chain so the spinner state lands before the LLM call.
        def _replay_pending():
            return (
                "_⏳ Replaying through current pipeline (8–25s)…_",
                gr.update(interactive=False),
            )

        def _replay_run(record):
            if record is None:
                return "", gr.update(interactive=True)
            try:
                result = replay(record)
                return format_replay_comparison(result), gr.update(interactive=True)
            except Exception as exc:  # surface any failure as visible markdown
                return (
                    f"### Replay failed\n\n```\n{type(exc).__name__}: {exc}\n```",
                    gr.update(interactive=True),
                )

        (
            replay_btn.click(
                fn=_replay_pending, outputs=[replay_md, replay_btn]
            ).then(
                fn=_replay_run,
                inputs=[selected_record],
                outputs=[replay_md, replay_btn],
            )
        )

        # ---- Trend Explorer (issue #30) ------------------------------------
        gr.Markdown("---\n## Trend Explorer · last 30 days")

        selected_metric = gr.State(None)

        # Scan mode: 5 thematic blocks of mini charts; each unit = header markdown + LinePlot
        # + Investigate button. Stash buttons by metric so we can wire each click handler.
        scan_buttons: dict[str, gr.Button] = {}

        with gr.Column(visible=True) as scan_view:
            for block_name, block_metrics in THEMATIC_BLOCKS.items():
                gr.Markdown(f"### {block_name}")
                with gr.Row():
                    for metric in block_metrics:
                        with gr.Column(min_width=220):
                            gr.Markdown(format_trend_header(metric, model))
                            gr.LinePlot(
                                value=chart_dataframe(model, metric, days=30),
                                x="date", y="value", color="series",
                                height=140,
                                show_label=False,
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
                height=420, show_label=False,
            )
            back_to_scan_btn = gr.Button("← Back to scan", variant="secondary")

        # Investigate-mode renderer used by metric-button clicks AND filter changes.
        def _build_investigate_chart(
            metric: str | None, window_label: str, show_prior: bool
        ):
            if not metric:
                return gr.update(), pd.DataFrame(columns=["date", "value", "series"])
            days = dict(TREND_WINDOWS).get(window_label, 30)
            current_records = DashboardModel(reader.read())
            prior = current_records.for_prior_window(days=days) if show_prior else None
            df = chart_dataframe(current_records, metric, days=days, prior_model=prior)
            title = (
                f"### Investigating: {METRIC_LABELS[metric]}\n"
                + format_trend_header(metric, current_records, prior_model=prior)
            )
            return title, df

        # Per-metric Investigate button: enter investigate view + render initial chart.
        def _enter_investigate_for(metric: str):
            def _handler(window_label, show_prior):
                title, df = _build_investigate_chart(metric, window_label, show_prior)
                return (
                    metric,                      # selected_metric state
                    gr.update(visible=False),    # hide scan
                    gr.update(visible=True),     # show investigate
                    title,
                    df,
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

        # Window or prior toggle change → re-render investigate chart in place.
        def _refresh_investigate(metric, window_label, show_prior):
            title, df = _build_investigate_chart(metric, window_label, show_prior)
            return title, df

        for control in (window_radio, prior_chk):
            control.change(
                fn=_refresh_investigate,
                inputs=[selected_metric, window_radio, prior_chk],
                outputs=[investigate_title, investigate_chart],
            )

        # ← Back to scan: reverse the swap; selected_metric retained for if user re-enters.
        def _back_to_scan():
            return gr.update(visible=True), gr.update(visible=False)

        back_to_scan_btn.click(
            fn=_back_to_scan, outputs=[scan_view, investigate_view]
        )

        # ---- Cluster panel (issue #32) -------------------------------------
        gr.Markdown("---\n## Gap Clusters")
        cluster_md = gr.Markdown(format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH)))

        def _refresh_clusters():
            return format_cluster_panel(read_clusters(CLUSTERS_DEFAULT_PATH))

        # Re-read the cached cluster file when the operator hits Refresh — the
        # batch may have been re-run between dashboard sessions.
        refresh_btn.click(fn=_refresh_clusters, outputs=[cluster_md])

    return app


if __name__ == "__main__":
    build_app().launch(inbrowser=True)

"""Local Gradio dashboard over the canonical interaction log (Phase 4 / issue #29).

Boots against `LogReader` (defaults to `LocalReader` over the JSONL backend; HF
Dataset is Phase 6). Manual refresh only — no auto-poll. Run locally with:

    uv run python src/sentinel.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import gradio as gr

from dashboard_model import DashboardModel
from log_reader import HFReader, LocalReader, LogReader
from metric_status import WoWDelta, metric_status, wow_delta

WINDOWS = [("Global", None), ("30d", 30), ("7d", 7)]


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


def _load(reader: LogReader) -> tuple[DashboardModel, datetime]:
    return DashboardModel(reader.read()), datetime.now(timezone.utc)


def _render_panels(model: DashboardModel) -> list[str]:
    """Render one panel per window, attaching the matching prior-window model
    for WoW deltas (None for Global)."""
    return [
        format_panel(label, model.for_window(days=days), prior_model=model.for_prior_window(days=days))
        for label, days in WINDOWS
    ]


def build_app(reader: LogReader | None = None) -> gr.Blocks:
    reader = reader or _default_reader()
    source = _source_label(reader)
    model, loaded_at = _load(reader)

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

        def _refresh():
            new_model, new_loaded_at = _load(reader)
            return [format_header(source, new_loaded_at), *_render_panels(new_model)]

        refresh_btn.click(fn=_refresh, outputs=[header_md, *panels])

    return app


if __name__ == "__main__":
    build_app().launch(inbrowser=True)

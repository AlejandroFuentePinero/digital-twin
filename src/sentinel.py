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

WINDOWS = [("Today", 1), ("7d", 7), ("30d", 30)]


def _default_reader() -> LogReader:
    if os.environ.get("HF_WRITE_TOKEN"):
        return HFReader()
    return LocalReader()


def _source_label(reader: LogReader) -> str:
    return "HF Dataset" if isinstance(reader, HFReader) else "Local JSONL"


def format_header(source: str, loaded_at: datetime) -> str:
    when = loaded_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"**Source:** {source}  ·  **Last loaded:** {when}"


def _fmt_pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _fmt_ms(ms: float | None) -> str:
    return "—" if ms is None else f"{ms:.0f} ms"


def format_panel(label: str, model: DashboardModel) -> str:
    return (
        f"### {label}\n\n"
        f"- **Total interactions:** {model.total_interactions}\n"
        f"- **Gap rate:** {_fmt_pct(model.gap_rate)}\n"
        f"- **Deflection rate:** {_fmt_pct(model.deflection_rate)}\n"
        f"- **Guardrail rejection rate:** {_fmt_pct(model.guardrail_rejection_rate)}\n"
        f"- **Latency p50:** {_fmt_ms(model.latency_p50)}\n"
        f"- **Latency p95:** {_fmt_ms(model.latency_p95)}\n"
    )


def _load(reader: LogReader) -> tuple[DashboardModel, datetime]:
    return DashboardModel(reader.read()), datetime.now(timezone.utc)


def build_app(reader: LogReader | None = None) -> gr.Blocks:
    reader = reader or _default_reader()
    source = _source_label(reader)
    model, loaded_at = _load(reader)

    with gr.Blocks(title="Digital Twin · Sentinel") as app:
        with gr.Row():
            gr.Markdown("# Digital Twin · Sentinel")
            refresh_btn = gr.Button("↻ Refresh", variant="secondary", size="sm", scale=0)
        header_md = gr.Markdown(format_header(source, loaded_at))

        with gr.Row():
            panels: list[gr.Markdown] = []
            for label, days in WINDOWS:
                with gr.Column():
                    panels.append(gr.Markdown(format_panel(label, model.for_window(days=days))))

        def _refresh():
            new_model, new_loaded_at = _load(reader)
            return [
                format_header(source, new_loaded_at),
                *(format_panel(label, new_model.for_window(days=days)) for label, days in WINDOWS),
            ]

        refresh_btn.click(fn=_refresh, outputs=[header_md, *panels])

    return app


if __name__ == "__main__":
    build_app().launch(inbrowser=True)

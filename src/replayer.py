"""Replay a logged failure through the current Pipeline (issue #38).

Given an `InteractionRecord` from the live log, reconstructs the prior-turn
conversation context, runs the same question through the current `Pipeline`,
and returns both records side-by-side for the Sentinel UI to render.

The replay deliberately does *not* persist the new record — it captures it in
memory via `CapturingLogWriter` so the live interaction log isn't polluted with
non-organic turns. Replays are for verification, not telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from interaction_log import InteractionRecord
from log_reader import LocalReader, LogReader


@dataclass(frozen=True)
class ReplayResult:
    """Original record + freshly-generated record for side-by-side comparison."""
    original: InteractionRecord
    current: InteractionRecord


class CapturingLogWriter:
    """In-memory log writer for replay. Validates the record (so replay surfaces schema
    bugs the same way the real LogWriter would) but never writes to disk."""

    def __init__(self) -> None:
        self.captured: InteractionRecord | None = None

    def append(self, record: dict | InteractionRecord) -> None:
        if isinstance(record, dict):
            record = InteractionRecord.model_validate(record)
        self.captured = record


def reconstruct_history(
    record: InteractionRecord, reader: LogReader
) -> list[dict]:
    """Build the conversation history for ``record``: every prior turn in the same
    session, ordered ascending by ``turn_index``, formatted as alternating
    user/assistant message dicts. The assistant content uses the last attempt's
    answer (what the user actually saw)."""
    prior = [
        r
        for r in reader.read()
        if r.session_id == record.session_id and r.turn_index < record.turn_index
    ]
    prior.sort(key=lambda r: r.turn_index)
    history: list[dict] = []
    for r in prior:
        history.append({"role": "user", "content": r.question})
        if r.attempts:
            history.append({"role": "assistant", "content": r.attempts[-1]["answer"]})
    return history


def replay(
    record: InteractionRecord,
    *,
    reader: LogReader | None = None,
    pipeline_factory: Callable | None = None,
) -> ReplayResult:
    """Re-run ``record.question`` through the current Pipeline using the same prior-turn
    history. Returns a `ReplayResult` holding both records.

    The new record is captured in-memory (`CapturingLogWriter`) and never written to disk
    — replays are for verification, not telemetry.
    """
    reader = reader or LocalReader()
    pipeline_factory = pipeline_factory or _default_pipeline_factory
    history = reconstruct_history(record, reader)
    log_writer = CapturingLogWriter()
    pipeline = pipeline_factory(log_writer=log_writer)
    pipeline.run(
        question=record.question,
        history=history,
        session_id=record.session_id,
        turn_index=record.turn_index,
        contact_offered=record.contact_offered,
        contact_provided=record.contact_provided,
    )
    if log_writer.captured is None:
        raise RuntimeError(
            "Replay completed but no record was captured — "
            "pipeline_factory's Pipeline.run did not write to log_writer."
        )
    return ReplayResult(original=record, current=log_writer.captured)


def _default_pipeline_factory(*, log_writer):
    """Build a fully-wired Pipeline against current code + the supplied log writer.
    Imports kept lazy so test code that injects its own factory doesn't need to load
    the heavy LLM/tool deps."""
    from pathlib import Path

    from branches import REGISTRY
    from classifier import Classifier
    from composer import PromptComposer
    from generator import Generator
    from guardrail import Guardrail
    from pipeline import Pipeline
    from profile import ProfileLoader
    from tools import ToolRegistry, make_litellm_tool_callable

    profile = ProfileLoader()
    composer = PromptComposer(profile, REGISTRY)
    tool_registry = ToolRegistry(
        Path(__file__).parent.parent / "data" / "readmes" / "registry.json"
    )
    return Pipeline(
        classifier=Classifier(),
        composer=composer,
        generator=Generator(),
        guardrail=Guardrail(),
        log_writer=log_writer,
        tool_registry=tool_registry,
        tool_model_callable=make_litellm_tool_callable(),
    )

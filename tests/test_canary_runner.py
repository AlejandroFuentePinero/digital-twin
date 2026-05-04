"""Tests for the canary runner orchestrator (issue #39).

The runner replays the canary corpus N replicates per question through the
current Pipeline, writing canary-tagged InteractionRecords to the canonical
log. Tests inject a fake `pipeline_factory` so the suite never hits a real
LLM (per `docs/TESTING.md`); the contract is that the runner sets is_canary
on every record, all replicates of one batch share one run_id, and the
replicate_index sequence is contiguous from 0.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from interaction_log import LogReader


def _corpus_at(path: Path, n: int = 2) -> Path:
    rows = []
    for i in range(n):
        rows.append({
            "id": f"C{i+1:03d}",
            "question": f"q{i+1}",
            "expected_branch": "GENERIC",
            "expected_event_type": "answered",
            "expected_chunk_sources": [],
            "expected_keywords": [],
            "category": "smoke",
            "requires_tool": False,
        })
    path.write_text(json.dumps(rows))
    return path


def _record_dict(question: str) -> dict:
    return {
        "schema_version": "3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "canary",
        "turn_index": 0,
        "question": question,
        "event_type": "answered",
        "branch": "GENERIC",
        "classifier_labels": ["GENERIC"],
        "classification_confidence": 0.9,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0,
                       "guardrail": 0, "total": 0},
        "knew_answer": True,
    }


class _FakePipeline:
    """Minimal stand-in for `Pipeline`. Receives the canary-aware writer at
    construction; in `run()` it appends one record per call so the runner's
    replicate loop produces exactly the same number of log lines as a real
    pipeline would (modulo per-attempt re-generation, which is irrelevant to
    the runner's contract)."""

    def __init__(self, writer):
        self.writer = writer

    def run(self, question: str, history, session_id, turn_index, **_):
        self.writer.append(_record_dict(question))
        return "ok"


def test_run_batch_writes_n_replicates_per_question_with_shared_run_id(tmp_path: Path):
    """Two questions × three replicates → six records, all is_canary=True, all
    sharing one run_id, replicate_index 0..2 per question."""
    from canary_runner import run_batch

    corpus = _corpus_at(tmp_path / "corpus.json", n=2)
    log_path = tmp_path / "interactions.jsonl"

    run_id = run_batch(
        replicates=3,
        corpus_path=corpus,
        log_path=log_path,
        pipeline_factory=lambda writer: _FakePipeline(writer),
    )

    records = LogReader(log_path).read_all()
    assert len(records) == 6
    for r in records:
        assert r["is_canary"] is True
        assert r["run_id"] == run_id

    by_question: dict[str, list[int]] = defaultdict(list)
    for r in records:
        by_question[r["question"]].append(r["replicate_index"])
    for q, indices in by_question.items():
        assert sorted(indices) == [0, 1, 2], (
            f"question {q} replicate indices: {sorted(indices)}"
        )


def test_run_batch_appends_to_existing_log_without_clobbering_live_records(tmp_path: Path):
    """The runner writes to the canonical log alongside live records — the
    live tabs filter canary records out via DashboardModel's default
    include_canary=False. Defends against a refactor that opens the file in
    write mode instead of append."""
    from canary_runner import run_batch

    log_path = tmp_path / "interactions.jsonl"
    log_path.write_text(json.dumps(_record_dict("live q")) + "\n")

    corpus = _corpus_at(tmp_path / "corpus.json", n=1)
    run_batch(
        replicates=2,
        corpus_path=corpus,
        log_path=log_path,
        pipeline_factory=lambda writer: _FakePipeline(writer),
    )

    records = LogReader(log_path).read_all()
    assert len(records) == 3  # 1 live + 2 canary
    live = [r for r in records if not r.get("is_canary")]
    canary = [r for r in records if r.get("is_canary")]
    assert len(live) == 1 and live[0]["question"] == "live q"
    assert len(canary) == 2


def test_run_batch_freezes_baseline_when_flag_is_set(tmp_path: Path):
    """--freeze-baseline promotes the just-completed run to the frozen
    baseline. Pointer carries the run_id so resolve_baseline_records can
    recover this run's records on the next launch."""
    from canary_baseline import read_baseline
    from canary_runner import run_batch

    corpus = _corpus_at(tmp_path / "corpus.json", n=1)
    log_path = tmp_path / "interactions.jsonl"
    baseline_path = tmp_path / "baseline.json"

    run_id = run_batch(
        replicates=1,
        corpus_path=corpus,
        log_path=log_path,
        pipeline_factory=lambda writer: _FakePipeline(writer),
        freeze_baseline_after=True,
        baseline_path=baseline_path,
    )

    pointer = read_baseline(baseline_path)
    assert pointer is not None
    assert pointer["run_id"] == run_id


def test_run_batch_does_not_freeze_baseline_when_flag_is_not_set(tmp_path: Path):
    """Default behaviour: a canary run lands in the log but does not promote
    itself to the baseline. The operator decides when a run becomes golden."""
    from canary_runner import run_batch

    corpus = _corpus_at(tmp_path / "corpus.json", n=1)
    log_path = tmp_path / "interactions.jsonl"
    baseline_path = tmp_path / "baseline.json"

    run_batch(
        replicates=1,
        corpus_path=corpus,
        log_path=log_path,
        pipeline_factory=lambda writer: _FakePipeline(writer),
        baseline_path=baseline_path,
    )

    assert not baseline_path.exists()


def test_run_batch_default_replicates_is_three():
    """Three replicates default — encoded so a refactor that drops the
    constant trips a test rather than silently moving signal characteristics."""
    import inspect

    from canary_runner import run_batch

    sig = inspect.signature(run_batch)
    assert sig.parameters["replicates"].default == 3

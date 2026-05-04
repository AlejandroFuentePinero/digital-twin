"""Tests for the canary baseline pointer (issue #39).

baseline.json is a tiny pointer file: it names which `run_id` is the frozen
golden baseline, when it was frozen, and at which `git_sha`. Missing or stale
pointers degrade quietly so Sentinel never crashes on cold start."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from canary_baseline import (
    DEFAULT_BASELINE_PATH,
    freeze_baseline,
    read_baseline,
    resolve_baseline_records,
)


def _record(run_id: str = "run-A", question: str = "q", branch: str = "GENERIC"):
    from interaction_log import InteractionRecord

    return InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "canary",
        "turn_index": 0,
        "question": question,
        "event_type": "answered",
        "branch": branch,
        "classification_confidence": 0.9,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0,
                       "guardrail": 0, "total": 0},
        "knew_answer": True,
        "is_canary": True,
        "run_id": run_id,
        "replicate_index": 0,
    })


def test_freeze_and_read_baseline_round_trips_run_id_and_metadata(tmp_path: Path):
    """freeze_baseline(run_id) writes a JSON pointer with run_id, frozen_at,
    and frozen_git_sha. read_baseline returns the same dict so the canary
    panel can render the baseline metadata in its drift summary banner."""
    pointer = tmp_path / "baseline.json"
    freeze_baseline(
        "run-2026-05-04-abc",
        frozen_git_sha="deadbeef",
        path=pointer,
        notes="post-Phase-4 baseline",
    )
    out = read_baseline(pointer)
    assert out["run_id"] == "run-2026-05-04-abc"
    assert out["frozen_git_sha"] == "deadbeef"
    assert out["notes"] == "post-Phase-4 baseline"
    # frozen_at is an ISO-8601 timestamp
    datetime.fromisoformat(out["frozen_at"])


def test_read_baseline_returns_none_when_pointer_absent(tmp_path: Path):
    """Cold-start: no baseline.json yet → None. The canary panel reads None
    and renders 'no baseline frozen' instead of crashing."""
    assert read_baseline(tmp_path / "missing.json") is None


def test_resolve_baseline_records_returns_subset_matching_pointer_run_id(tmp_path: Path):
    """resolve_baseline_records filters all canary records down to just those
    that share the baseline's run_id. Drift detection compares the current
    run against this subset."""
    pointer = tmp_path / "baseline.json"
    freeze_baseline("run-A", frozen_git_sha="sha-A", path=pointer)
    records = [
        _record(run_id="run-A", question="q1"),
        _record(run_id="run-A", question="q2"),
        _record(run_id="run-B", question="q1"),  # different run — excluded
    ]
    baseline_records = resolve_baseline_records(records, pointer)
    assert len(baseline_records) == 2
    assert {r.question for r in baseline_records} == {"q1", "q2"}


def test_resolve_baseline_records_returns_empty_list_when_pointer_stale(tmp_path: Path):
    """Stale pointer (run_id no longer in the log — e.g. operator pruned the
    log file) → []. Drift detection short-circuits to 'no comparison' rather
    than throwing on a missing baseline."""
    pointer = tmp_path / "baseline.json"
    freeze_baseline("run-vanished", frozen_git_sha="sha", path=pointer)
    records = [_record(run_id="run-A")]  # baseline's run_id absent
    assert resolve_baseline_records(records, pointer) == []


def test_resolve_baseline_records_returns_empty_list_when_pointer_missing(tmp_path: Path):
    """Missing pointer file → []. Same cold-start safety as read_baseline."""
    records = [_record(run_id="run-A")]
    assert resolve_baseline_records(records, tmp_path / "missing.json") == []


def test_default_baseline_path_lives_under_data_canaries():
    """The default pointer location is ``data/canaries/baseline.json`` —
    canonical alongside corpus.json. Lock the path into the test so a
    refactor doesn't quietly move it."""
    assert DEFAULT_BASELINE_PATH.name == "baseline.json"
    assert DEFAULT_BASELINE_PATH.parent.name == "canaries"

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
    runs_after_baseline,
)


def _record(
    run_id: str = "run-A",
    question: str = "q",
    branch: str = "GENERIC",
    timestamp: str | None = None,
):
    from interaction_log import InteractionRecord

    return InteractionRecord.model_validate({
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
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


# ----- runs_after_baseline (Session 51) -------------------------------------


def test_runs_after_baseline_returns_chronologically_ordered_run_ids(tmp_path: Path):
    """The N most recent post-baseline runs in chronological order — drives
    the +1 / +2 / +3 columns in the canary trajectory view."""
    pointer = tmp_path / "baseline.json"
    freeze_baseline("run-baseline", frozen_git_sha="sha", path=pointer)
    frozen_at = read_baseline(pointer)["frozen_at"]

    # Three post-baseline runs at known timestamps after the freeze.
    base_dt = datetime.fromisoformat(frozen_at)
    records = [
        _record(run_id="run-baseline", timestamp=frozen_at),  # baseline run itself
        _record(run_id="run-+2", timestamp=(base_dt.replace(microsecond=0) + (datetime.fromisoformat("2026-05-05T00:00:02") - datetime.fromisoformat("2026-05-05T00:00:00"))).isoformat()),
        _record(run_id="run-+1", timestamp=(base_dt.replace(microsecond=0) + (datetime.fromisoformat("2026-05-05T00:00:01") - datetime.fromisoformat("2026-05-05T00:00:00"))).isoformat()),
        _record(run_id="run-+3", timestamp=(base_dt.replace(microsecond=0) + (datetime.fromisoformat("2026-05-05T00:00:03") - datetime.fromisoformat("2026-05-05T00:00:00"))).isoformat()),
    ]
    result = runs_after_baseline(records, n=3, path=pointer)
    assert result == ["run-+1", "run-+2", "run-+3"]


def test_runs_after_baseline_caps_at_n(tmp_path: Path):
    """When more than N post-baseline runs exist, only the earliest N are
    returned — the trajectory view shows the first three runs after the
    baseline, not the latest three."""
    pointer = tmp_path / "baseline.json"
    freeze_baseline("run-baseline", frozen_git_sha="sha", path=pointer)
    frozen_at = read_baseline(pointer)["frozen_at"]
    base_dt = datetime.fromisoformat(frozen_at)

    records = [_record(run_id="run-baseline", timestamp=frozen_at)]
    for i in range(5):
        ts = (base_dt.replace(microsecond=0) + (datetime.fromisoformat(f"2026-05-05T00:00:0{i+1}") - datetime.fromisoformat("2026-05-05T00:00:00"))).isoformat()
        records.append(_record(run_id=f"run-+{i+1}", timestamp=ts))

    result = runs_after_baseline(records, n=3, path=pointer)
    assert result == ["run-+1", "run-+2", "run-+3"]
    assert len(result) == 3


def test_runs_after_baseline_returns_empty_when_no_post_baseline_runs(tmp_path: Path):
    """Freshly-frozen baseline + only the baseline run on disk → empty list.
    The trajectory view renders all em-dash placeholders until new runs land."""
    pointer = tmp_path / "baseline.json"
    freeze_baseline("run-baseline", frozen_git_sha="sha", path=pointer)
    frozen_at = read_baseline(pointer)["frozen_at"]
    records = [_record(run_id="run-baseline", timestamp=frozen_at)]
    assert runs_after_baseline(records, n=3, path=pointer) == []


def test_runs_after_baseline_returns_empty_when_pointer_absent(tmp_path: Path):
    """No pointer → no trajectory comparison possible. Cold-start safety."""
    records = [_record(run_id="run-anything")]
    assert runs_after_baseline(records, n=3, path=tmp_path / "missing.json") == []


def test_runs_after_baseline_ignores_runs_before_the_baseline(tmp_path: Path):
    """Records timestamped before the baseline freeze (e.g. an earlier
    canary run before the operator decided to lock the baseline) MUST NOT
    appear in the trajectory — they're historical, not post-baseline drift
    candidates."""
    pointer = tmp_path / "baseline.json"
    # Freeze the baseline at a known point in time (post the existing records).
    base_ts = "2026-05-05T12:00:00+00:00"
    pointer.write_text(json.dumps({
        "run_id": "run-baseline",
        "frozen_at": base_ts,
        "frozen_git_sha": "sha",
        "notes": "",
    }))
    records = [
        _record(run_id="run-old", timestamp="2026-05-05T11:00:00+00:00"),  # before
        _record(run_id="run-baseline", timestamp=base_ts),
        _record(run_id="run-after", timestamp="2026-05-05T13:00:00+00:00"),
    ]
    assert runs_after_baseline(records, n=3, path=pointer) == ["run-after"]

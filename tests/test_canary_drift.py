"""Tests for the canary drift detector (issue #39).

`canary_drift.py` is the deepest module in the canary feature: aggregates the
N replicates per question, then compares each question's aggregate to the
frozen baseline aggregate to emit `CanaryDriftFlag`s. The five drift kinds
each have minor/major severities locked at well-defined boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from canary_corpus import CanaryQuestion
from canary_drift import (
    AggregatedCanaryRun,
    CanaryDriftFlag,
    aggregate_question,
    detect_drift,
    stratified_summary,
)
from interaction_log import InteractionRecord


# ----- fixtures --------------------------------------------------------------


def _r(
    *,
    question: str = "q1",
    run_id: str = "run-A",
    replicate_index: int = 0,
    branch: str = "TECHNICAL",
    event_type: str = "answered",
    chunks: list[tuple[str, str]] | None = None,
    total_ms: int = 1000,
    attempts: int = 1,
    git_sha: str = "sha-A",
) -> InteractionRecord:
    return InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "canary",
        "turn_index": 0,
        "question": question,
        "event_type": event_type,
        "branch": branch,
        "classification_confidence": 0.9,
        "attempts": [
            {"answer": "ok", "is_acceptable": (i == attempts - 1),
             "guardrail_feedback": ""}
            for i in range(attempts)
        ],
        "retrieved_chunks": [
            {"source_file": sf, "section_heading": sh}
            for sf, sh in (chunks or [])
        ],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0,
                       "guardrail": 0, "total": total_ms},
        "knew_answer": True,
        "is_canary": True,
        "run_id": run_id,
        "replicate_index": replicate_index,
        "git_sha": git_sha,
    })


def _q(
    id: str = "C001",
    question: str = "q1",
    branch: str = "TECHNICAL",
    event_type: str = "answered",
    requires_tool: bool = False,
    category: str = "branch_routing",
) -> CanaryQuestion:
    return CanaryQuestion(
        id=id, question=question, expected_branch=branch,
        expected_event_type=event_type, expected_chunk_sources=[],
        expected_keywords=[], category=category, requires_tool=requires_tool,
    )


# ----- aggregate_question ----------------------------------------------------


def test_aggregate_question_picks_majority_branch_across_replicates():
    """The majority branch across N replicates is the aggregate's branch.
    Single-replicate disagreement on a 3-replicate run shouldn't flip the
    aggregate — that's why we replicate."""
    replicates = [
        _r(branch="TECHNICAL", replicate_index=0),
        _r(branch="TECHNICAL", replicate_index=1),
        _r(branch="GAP", replicate_index=2),
    ]
    agg = aggregate_question(replicates)
    assert agg.branch == "TECHNICAL"


def test_aggregate_question_picks_majority_event_type_across_replicates():
    replicates = [
        _r(event_type="answered", replicate_index=0),
        _r(event_type="gap", replicate_index=1),
        _r(event_type="gap", replicate_index=2),
    ]
    assert aggregate_question(replicates).event_type == "gap"


def test_aggregate_question_uses_median_total_latency():
    replicates = [
        _r(total_ms=500, replicate_index=0),
        _r(total_ms=1000, replicate_index=1),
        _r(total_ms=5000, replicate_index=2),
    ]
    assert aggregate_question(replicates).median_latency_ms == 1000


def test_aggregate_question_intersects_chunk_sets_across_replicates():
    """Intersection over the N replicates — only chunks every replicate
    retrieved survive into the aggregate. Drift is then detected against the
    *stable* set, not the union, so a single flaky retrieval doesn't move
    the baseline."""
    replicates = [
        _r(chunks=[("a.md", "Alpha"), ("b.md", "Beta")], replicate_index=0),
        _r(chunks=[("a.md", "Alpha"), ("c.md", "Gamma")], replicate_index=1),
        _r(chunks=[("a.md", "Alpha"), ("b.md", "Beta")], replicate_index=2),
    ]
    assert aggregate_question(replicates).chunk_set == frozenset([("a.md", "Alpha")])


def test_aggregate_question_takes_max_attempts_across_replicates():
    replicates = [
        _r(attempts=1, replicate_index=0),
        _r(attempts=2, replicate_index=1),
        _r(attempts=3, replicate_index=2),
    ]
    assert aggregate_question(replicates).max_attempts == 3


# ----- detect_drift: branch_changed -----------------------------------------


def test_detect_drift_flags_branch_change_as_major():
    corpus = [_q()]
    baseline = [_r(branch="TECHNICAL", run_id="run-A")]
    current = [_r(branch="GAP", run_id="run-B")]
    flags = detect_drift(current, baseline, corpus)
    branch_flags = [f for f in flags if f.kind == "branch_changed"]
    assert len(branch_flags) == 1
    assert branch_flags[0].severity == "major"
    assert branch_flags[0].question == "q1"


def test_detect_drift_silent_when_branch_unchanged():
    corpus = [_q()]
    baseline = [_r(branch="TECHNICAL", run_id="run-A")]
    current = [_r(branch="TECHNICAL", run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "branch_changed"]
    assert flags == []


# ----- detect_drift: event_type_changed -------------------------------------


def test_detect_drift_flags_event_type_change_as_major():
    corpus = [_q()]
    baseline = [_r(event_type="answered", run_id="run-A")]
    current = [_r(event_type="gap", run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "event_type_changed"]
    assert len(flags) == 1
    assert flags[0].severity == "major"


# ----- detect_drift: retry_depth_changed ------------------------------------


def test_detect_drift_flags_retry_depth_minor_when_delta_is_one():
    corpus = [_q()]
    baseline = [_r(attempts=1, run_id="run-A")]
    current = [_r(attempts=2, run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "retry_depth_changed"]
    assert len(flags) == 1
    assert flags[0].severity == "minor"


def test_detect_drift_flags_retry_depth_major_when_jumping_to_three_plus():
    """Jump from clean (1 attempt) to retry-exhausted (3 attempts) = major."""
    corpus = [_q()]
    baseline = [_r(attempts=1, run_id="run-A")]
    current = [_r(attempts=3, run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "retry_depth_changed"]
    assert len(flags) == 1
    assert flags[0].severity == "major"


def test_detect_drift_flags_retry_depth_major_when_dropping_from_three_plus():
    """Reverse jump (was retry-exhausted, now clean) is also major — same
    delta magnitude, same operator-attention-worthy event (something changed
    enough to re-pass on first attempt)."""
    corpus = [_q()]
    baseline = [_r(attempts=3, run_id="run-A")]
    current = [_r(attempts=1, run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "retry_depth_changed"]
    assert len(flags) == 1
    assert flags[0].severity == "major"


def test_detect_drift_silent_when_retry_depth_unchanged():
    corpus = [_q()]
    baseline = [_r(attempts=2, run_id="run-A")]
    current = [_r(attempts=2, run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "retry_depth_changed"]
    assert flags == []


# ----- detect_drift: chunk_set_changed --------------------------------------


def test_detect_drift_flags_chunk_set_minor_when_jaccard_in_minor_band():
    """Jaccard ∈ [0.4, 0.7) → minor. Two-out-of-five overlap = 2/8 = 0.25 →
    major; we want a minor here. Use sets of size 4 with 2 overlap → 2/6 = 0.33
    → still major. Use 3-of-4 overlap: 3/5 = 0.6 ∈ [0.4, 0.7) → minor."""
    corpus = [_q()]
    baseline = [_r(chunks=[("a.md", "A"), ("b.md", "B"), ("c.md", "C")],
                    run_id="run-A")]
    current = [_r(chunks=[("a.md", "A"), ("b.md", "B"), ("c.md", "C"), ("d.md", "D"), ("e.md", "E")],
                   run_id="run-B")]
    # baseline ∩ current = {a, b, c} (size 3); ∪ = {a, b, c, d, e} (size 5)
    # Jaccard = 3/5 = 0.6 ∈ [0.4, 0.7) → minor
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "chunk_set_changed"]
    assert len(flags) == 1
    assert flags[0].severity == "minor"


def test_detect_drift_flags_chunk_set_major_when_jaccard_below_minor_band():
    """Jaccard < 0.4 → major. baseline {a, b}, current {c, d, e} → no overlap →
    Jaccard = 0 → major."""
    corpus = [_q()]
    baseline = [_r(chunks=[("a.md", "A"), ("b.md", "B")], run_id="run-A")]
    current = [_r(chunks=[("c.md", "C"), ("d.md", "D"), ("e.md", "E")],
                   run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "chunk_set_changed"]
    assert len(flags) == 1
    assert flags[0].severity == "major"


def test_detect_drift_silent_when_chunk_set_identical():
    corpus = [_q()]
    chunks = [("a.md", "A"), ("b.md", "B")]
    baseline = [_r(chunks=chunks, run_id="run-A")]
    current = [_r(chunks=chunks, run_id="run-B")]
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "chunk_set_changed"]
    assert flags == []


# ----- detect_drift: latency_p95_regression ---------------------------------


def test_detect_drift_flags_latency_minor_when_median_grows_more_than_25_percent():
    """Aggregated median latency grew >25% but ≤50% → minor."""
    corpus = [_q()]
    baseline = [_r(total_ms=1000, run_id="run-A")]
    current = [_r(total_ms=1300, run_id="run-B")]   # 30% increase → minor
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "latency_p95_regression"]
    assert len(flags) == 1
    assert flags[0].severity == "minor"


def test_detect_drift_flags_latency_major_when_median_grows_more_than_50_percent():
    corpus = [_q()]
    baseline = [_r(total_ms=1000, run_id="run-A")]
    current = [_r(total_ms=1700, run_id="run-B")]   # 70% increase → major
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "latency_p95_regression"]
    assert len(flags) == 1
    assert flags[0].severity == "major"


def test_detect_drift_silent_when_latency_within_tolerance():
    corpus = [_q()]
    baseline = [_r(total_ms=1000, run_id="run-A")]
    current = [_r(total_ms=1100, run_id="run-B")]   # 10% — within 25%
    flags = [f for f in detect_drift(current, baseline, corpus)
             if f.kind == "latency_p95_regression"]
    assert flags == []


# ----- detect_drift: empty / mismatched inputs ------------------------------


def test_detect_drift_returns_empty_when_baseline_is_empty():
    """Cold start: no baseline records → no comparison → no flags. The canary
    panel reads `[]` and renders 'no baseline frozen' instead of crashing."""
    corpus = [_q()]
    current = [_r(run_id="run-B")]
    assert detect_drift(current, [], corpus) == []


def test_detect_drift_skips_questions_present_only_in_one_run():
    """If a question appears in baseline but not current (or vice versa) the
    detector must skip it — comparing aggregates across questions is invalid.
    Drift is per-question."""
    corpus = [_q(question="q1"), _q(question="q2")]
    baseline = [_r(question="q1", branch="TECHNICAL", run_id="run-A")]
    current = [_r(question="q2", branch="GAP", run_id="run-B")]
    # No question is in BOTH runs → no drift flags fire
    assert detect_drift(current, baseline, corpus) == []


def test_detect_drift_aggregates_replicates_before_comparing():
    """Three baseline replicates vs three current replicates → one comparison
    per question, not nine. Defends against the obvious bug where the
    detector pairs records by replicate_index."""
    corpus = [_q()]
    baseline = [
        _r(branch="TECHNICAL", replicate_index=i, run_id="run-A")
        for i in range(3)
    ]
    current = [
        _r(branch="GAP", replicate_index=i, run_id="run-B") for i in range(3)
    ]
    flags = detect_drift(current, baseline, corpus)
    branch_flags = [f for f in flags if f.kind == "branch_changed"]
    assert len(branch_flags) == 1


# ----- stratified_summary ----------------------------------------------------


def test_stratified_summary_groups_drift_counts_by_expected_branch_and_category():
    """Stratified summary lets the operator scan 'which branch is drifting' /
    'which category is drifting' as chips above the per-flag cards."""
    corpus = [
        _q(question="q1", branch="TECHNICAL", category="numerical_fidelity"),
        _q(question="q2", branch="GAP", category="branch_routing_gap"),
    ]
    flags = [
        CanaryDriftFlag(question="q1", kind="branch_changed", severity="major",
                        headline="x", detail="x"),
        CanaryDriftFlag(question="q1", kind="latency_p95_regression",
                        severity="minor", headline="x", detail="x"),
        CanaryDriftFlag(question="q2", kind="branch_changed", severity="major",
                        headline="x", detail="x"),
    ]
    summary = stratified_summary(flags, corpus)
    assert summary["by_branch"]["TECHNICAL"] == 2
    assert summary["by_branch"]["GAP"] == 1
    assert summary["by_category"]["numerical_fidelity"] == 2
    assert summary["by_category"]["branch_routing_gap"] == 1

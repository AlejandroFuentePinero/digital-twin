"""Canary drift detector — pure functions over canary records (issue #39).

Two phases:

1. **Aggregate** the N replicates of each canary question into a single
   `AggregatedCanaryRun` (majority branch, majority event_type, median total
   latency, intersected chunk-set, max attempts). Replicates exist precisely
   so single-shot LLM stochasticity doesn't generate spurious drift flags.

2. **Detect** drift per-question by comparing the current run's aggregate to
   the baseline run's aggregate. Five drift kinds with locked severity bounds:

   - ``branch_changed``         → always major
   - ``event_type_changed``     → always major
   - ``retry_depth_changed``    → minor (delta ±1), major (1↔3+ jump)
   - ``chunk_set_changed``      → minor (Jaccard ∈ [0.4, 0.7)), major (< 0.4)
   - ``latency_p95_regression`` → minor (>25% growth), major (>50% growth)

Per the PRD, drift detection is keyword-free / answer-text-free at v1 — every
signal comes from the routed branch, the event_type, the chunk set, the
retry depth, and the per-question latency. An LLM-judge layer can be added
later as `answer_drifted` if keyword matching proves too brittle.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Literal

from canary_corpus import CanaryQuestion
from interaction_log import InteractionRecord


DriftKind = Literal[
    "branch_changed",
    "event_type_changed",
    "retry_depth_changed",
    "chunk_set_changed",
    "latency_p95_regression",
]
Severity = Literal["minor", "major"]

# Locked thresholds — see issue #39 § Drift detection.
JACCARD_MAJOR_BELOW = 0.4
JACCARD_MINOR_BELOW = 0.7
LATENCY_MINOR_MULTIPLIER = 1.25
LATENCY_MAJOR_MULTIPLIER = 1.50


@dataclass(frozen=True)
class AggregatedCanaryRun:
    """One canary question's aggregate across N replicates of one run."""
    question: str
    run_id: str | None
    branch: str
    event_type: str
    median_latency_ms: float
    chunk_set: frozenset[tuple[str, str]]
    max_attempts: int
    git_sha: str | None


@dataclass(frozen=True)
class CanaryDriftFlag:
    """One drift signal between baseline and current aggregates for a question."""
    question: str
    kind: DriftKind
    severity: Severity
    headline: str
    detail: str


def _majority(values: Iterable) -> str:
    """Most common element. Ties broken by first-seen — Counter.most_common
    returns insertion-order on tied counts in Python 3.7+."""
    [(top, _)] = Counter(values).most_common(1)
    return top


def aggregate_question(records: list[InteractionRecord]) -> AggregatedCanaryRun:
    """Roll up N replicates of one canary question into a single aggregate.

    Caller's responsibility: every record in `records` is for the same
    question and the same run (same `question` field, same `run_id`).
    """
    if not records:
        raise ValueError("aggregate_question requires at least one replicate")
    chunk_sets = [
        frozenset(
            (c.get("source_file", ""), c.get("section_heading", ""))
            for c in r.retrieved_chunks
        )
        for r in records
    ]
    intersection: frozenset[tuple[str, str]] = chunk_sets[0]
    for s in chunk_sets[1:]:
        intersection = intersection & s

    return AggregatedCanaryRun(
        question=records[0].question,
        run_id=records[0].run_id,
        branch=_majority(r.branch for r in records),
        event_type=_majority(r.event_type for r in records),
        median_latency_ms=median(r.latency_ms.get("total", 0) for r in records),
        chunk_set=intersection,
        max_attempts=max(len(r.attempts) for r in records),
        git_sha=records[0].git_sha,
    )


def _group_by_question(
    records: list[InteractionRecord],
) -> dict[str, list[InteractionRecord]]:
    grouped: dict[str, list[InteractionRecord]] = {}
    for r in records:
        grouped.setdefault(r.question, []).append(r)
    return grouped


def _retry_depth_severity(baseline_max: int, current_max: int) -> Severity | None:
    if baseline_max == current_max:
        return None
    delta = abs(baseline_max - current_max)
    # Major when crossing the 1 ↔ 3+ boundary (clean ↔ retry-exhausted).
    if (baseline_max <= 1 and current_max >= 3) or (baseline_max >= 3 and current_max <= 1):
        return "major"
    if delta == 1:
        return "minor"
    # Larger jumps not crossing the 1↔3+ boundary (e.g. 2 → some hypothetical
    # 5) read as major; v1 has MAX_ATTEMPTS=3 so this branch is unreachable
    # today. Treating it as major keeps the threshold monotone if the cap moves.
    return "major"


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _chunk_severity(jaccard: float) -> Severity | None:
    if jaccard >= JACCARD_MINOR_BELOW:
        return None
    if jaccard < JACCARD_MAJOR_BELOW:
        return "major"
    return "minor"


def _latency_severity(baseline_ms: float, current_ms: float) -> Severity | None:
    if baseline_ms <= 0:
        return None
    ratio = current_ms / baseline_ms
    if ratio > LATENCY_MAJOR_MULTIPLIER:
        return "major"
    if ratio > LATENCY_MINOR_MULTIPLIER:
        return "minor"
    return None


def detect_drift(
    current_run: list[InteractionRecord],
    baseline_run: list[InteractionRecord],
    corpus: list[CanaryQuestion],
) -> list[CanaryDriftFlag]:
    """Per-question drift between current and baseline aggregates.

    Cold-start safety: empty baseline → no flags (nothing to compare to).
    Per-question matching: questions present in only one of (current,
    baseline) are skipped — comparing aggregates across questions is
    invalid. Drift is strictly per-question."""
    if not baseline_run or not current_run:
        return []

    current_groups = _group_by_question(current_run)
    baseline_groups = _group_by_question(baseline_run)
    common_questions = set(current_groups) & set(baseline_groups)

    flags: list[CanaryDriftFlag] = []
    for question in sorted(common_questions):
        cur = aggregate_question(current_groups[question])
        base = aggregate_question(baseline_groups[question])

        if cur.branch != base.branch:
            flags.append(CanaryDriftFlag(
                question=question, kind="branch_changed", severity="major",
                headline=f"Branch changed: {base.branch} → {cur.branch}",
                detail=(f"Canary {question!r} routed to {base.branch} on "
                        f"baseline run, now routes to {cur.branch}."),
            ))

        if cur.event_type != base.event_type:
            flags.append(CanaryDriftFlag(
                question=question, kind="event_type_changed", severity="major",
                headline=f"Event type changed: {base.event_type} → {cur.event_type}",
                detail=(f"Canary {question!r} reported {base.event_type} on "
                        f"baseline run, now reports {cur.event_type}."),
            ))

        retry_sev = _retry_depth_severity(base.max_attempts, cur.max_attempts)
        if retry_sev is not None:
            flags.append(CanaryDriftFlag(
                question=question, kind="retry_depth_changed", severity=retry_sev,
                headline=f"Retry depth changed: {base.max_attempts} → {cur.max_attempts}",
                detail=(f"Max attempts across replicates moved from "
                        f"{base.max_attempts} to {cur.max_attempts}."),
            ))

        jaccard = _jaccard(base.chunk_set, cur.chunk_set)
        chunk_sev = _chunk_severity(jaccard)
        if chunk_sev is not None:
            flags.append(CanaryDriftFlag(
                question=question, kind="chunk_set_changed", severity=chunk_sev,
                headline=f"Chunk set drifted (Jaccard {jaccard:.2f})",
                detail=(f"Stable retrieval set changed: baseline "
                        f"{sorted(base.chunk_set)} → current "
                        f"{sorted(cur.chunk_set)}."),
            ))

        latency_sev = _latency_severity(base.median_latency_ms, cur.median_latency_ms)
        if latency_sev is not None:
            growth = (cur.median_latency_ms - base.median_latency_ms) / base.median_latency_ms
            flags.append(CanaryDriftFlag(
                question=question, kind="latency_p95_regression", severity=latency_sev,
                headline=(
                    f"Latency regressed {growth * 100:.0f}% "
                    f"({base.median_latency_ms:.0f}ms → {cur.median_latency_ms:.0f}ms)"
                ),
                detail=(f"Median total latency across replicates moved from "
                        f"{base.median_latency_ms:.0f}ms to "
                        f"{cur.median_latency_ms:.0f}ms."),
            ))

    return flags


def stratified_summary(
    flags: list[CanaryDriftFlag], corpus: list[CanaryQuestion]
) -> dict[str, dict[str, int]]:
    """Drift counts grouped by expected_branch + by category — chips above
    the per-flag cards in the canary panel."""
    by_question = {q.question: q for q in corpus}
    by_branch: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    for f in flags:
        q = by_question.get(f.question)
        if q is None:
            continue
        by_branch[q.expected_branch] += 1
        by_category[q.category] += 1
    return {"by_branch": dict(by_branch), "by_category": dict(by_category)}

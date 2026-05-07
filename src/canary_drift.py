"""Canary drift detector — pure functions over canary records (issue #39,
extended in PRD #41 / #45).

Two phases:

1. **Aggregate** the N replicates of each canary question into a single
   `AggregatedCanaryRun` (majority branch, majority event_type, majority
   outcome, median total latency, intersected chunk-set, max attempts,
   median keyword coverage, OR'd red flag). Replicates exist precisely
   so single-shot LLM stochasticity doesn't generate spurious drift flags.

2. **Detect** drift per-question by comparing the current run's aggregate to
   the baseline run's aggregate. Six drift kinds with locked severity bounds:

   - ``branch_changed``               → always major
   - ``event_type_changed``           → always major (PRD #41 user-story #26)
   - ``outcome_changed``              → always major (post-#45 headline drift)
   - ``keyword_coverage_dropped``     → minor (drop ≥0.2), major (drop ≥0.5)
   - ``red_flag_emerged``             → always major (fabrication regression)
   - ``latency_p95_regression``       → minor (>50% growth), major (>100% growth)

The detector deliberately surfaces **outcome drift only** — branch/event/
outcome/keyword/red-flag answer the question "did the system stop doing
what we wanted?" Mechanism signals (which chunks were retrieved, how many
guardrail attempts ran, sub-second latency wobble) were dropped in
Session 62 because their false-positive rate dwarfed real signal: any
legitimate `ingest.py` rebuild flips chunk_set Jaccard via non-deterministic
enrichment headlines, and single-attempt retry variance is normal LLM mood.
Quality regressions caused by retrieval shifts now surface via
``keyword_coverage_dropped`` (downstream effect, not cause).

``latency_p95_regression`` survives but with tighter thresholds — sub-1.5x
ratios are API-load fluctuation, not regression.

Per the PRD, drift detection is keyword-free / answer-text-free for routing
signals; outcome / keyword-coverage / red-flag kinds (#45) inspect answer
text via the `canary_outcome` deep module. An LLM-judge layer can be added
later as `answer_drifted` if rule-based proves too brittle.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Literal

from canary_corpus import CanaryQuestion
from canary_outcome import (
    Outcome,
    derive_outcome,
    has_red_flag,
    keyword_hits,
)
from interaction_log import InteractionRecord


DriftKind = Literal[
    "branch_changed",
    "event_type_changed",
    "outcome_changed",
    "keyword_coverage_dropped",
    "red_flag_emerged",
    "latency_p95_regression",
]
Severity = Literal["minor", "major"]

# Thresholds — outcome bands locked by issue #39 § Drift detection + #45 § 5.
# Latency tightened in Session 62 (was 1.25 / 1.50) because sub-1.5x ratios
# turned out to be API-load wobble, not regression. Keyword bands unchanged.
LATENCY_MINOR_MULTIPLIER = 1.50
LATENCY_MAJOR_MULTIPLIER = 2.00
KEYWORD_COVERAGE_MINOR_DROP = 0.2
KEYWORD_COVERAGE_MAJOR_DROP = 0.5


@dataclass(frozen=True)
class AggregatedCanaryRun:
    """One canary question's aggregate across N replicates of one run."""
    question: str
    run_id: str | None
    branch: str
    event_type: str
    outcome: Outcome
    median_latency_ms: float
    keyword_coverage: float | None
    red_flag: bool
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


def aggregate_question(
    records: list[InteractionRecord], question: CanaryQuestion | None = None,
) -> AggregatedCanaryRun:
    """Roll up N replicates of one canary question into a single aggregate.

    Caller's responsibility: every record in `records` is for the same
    question and the same run (same `question` field, same `run_id`). When
    `question` is provided, outcome / keyword_coverage / red_flag are
    populated; when absent, they degrade to (`derive_outcome` from
    event_type alone with a synthetic empty CanaryQuestion via duck-shape,
    None coverage, False red_flag) — used by tests that only exercise the
    routing-stability fields.
    """
    if not records:
        raise ValueError("aggregate_question requires at least one replicate")

    if question is not None:
        outcomes = [derive_outcome(r, question) for r in records]
        outcome = _majority(outcomes)
        # OR across replicates: any replicate fabricating is a red flag
        # (the system *generated* the forbidden shape at least once).
        red_flag = any(has_red_flag(r, question) for r in records)
        if question.expected_outcome == "answered_with_substance" and question.expected_keywords:
            covs = []
            for r in records:
                matched, total = keyword_hits(r, question)
                if total > 0:
                    covs.append(matched / total)
            keyword_coverage: float | None = median(covs) if covs else None
        else:
            keyword_coverage = None
    else:
        # Question-less aggregation degrades to event_type-derived outcome.
        outcome = _outcome_from_event_type(_majority(r.event_type for r in records))
        red_flag = False
        keyword_coverage = None

    return AggregatedCanaryRun(
        question=records[0].question,
        run_id=records[0].run_id,
        branch=_majority(r.branch for r in records),
        event_type=_majority(r.event_type for r in records),
        outcome=outcome,
        median_latency_ms=median(r.latency_ms.get("total", 0) for r in records),
        keyword_coverage=keyword_coverage,
        red_flag=red_flag,
        git_sha=records[0].git_sha,
    )


def _outcome_from_event_type(event_type: str) -> Outcome:
    if event_type == "refused":
        return "refused"
    if event_type == "gap":
        return "gap_acknowledged"
    if event_type == "deflected":
        return "out_of_scope_redirect"
    return "answered_with_substance"


def _group_by_question(
    records: list[InteractionRecord],
) -> dict[str, list[InteractionRecord]]:
    grouped: dict[str, list[InteractionRecord]] = {}
    for r in records:
        grouped.setdefault(r.question, []).append(r)
    return grouped


def _latency_severity(baseline_ms: float, current_ms: float) -> Severity | None:
    if baseline_ms <= 0:
        return None
    ratio = current_ms / baseline_ms
    if ratio > LATENCY_MAJOR_MULTIPLIER:
        return "major"
    if ratio > LATENCY_MINOR_MULTIPLIER:
        return "minor"
    return None


def _keyword_coverage_severity(
    baseline_cov: float | None, current_cov: float | None
) -> Severity | None:
    if baseline_cov is None or current_cov is None:
        return None
    drop = baseline_cov - current_cov
    if drop >= KEYWORD_COVERAGE_MAJOR_DROP:
        return "major"
    if drop >= KEYWORD_COVERAGE_MINOR_DROP:
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
    corpus_by_question = {q.question: q for q in corpus}

    flags: list[CanaryDriftFlag] = []
    for question in sorted(common_questions):
        q = corpus_by_question.get(question)
        cur = aggregate_question(current_groups[question], q)
        base = aggregate_question(baseline_groups[question], q)

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

        if cur.outcome != base.outcome:
            flags.append(CanaryDriftFlag(
                question=question, kind="outcome_changed", severity="major",
                headline=f"Outcome changed: {base.outcome} → {cur.outcome}",
                detail=(f"Canary {question!r} produced outcome "
                        f"{base.outcome!r} on baseline run, now produces "
                        f"{cur.outcome!r}."),
            ))

        cov_sev = _keyword_coverage_severity(base.keyword_coverage, cur.keyword_coverage)
        if cov_sev is not None:
            drop = (base.keyword_coverage or 0) - (cur.keyword_coverage or 0)
            flags.append(CanaryDriftFlag(
                question=question, kind="keyword_coverage_dropped", severity=cov_sev,
                headline=(
                    f"Keyword coverage dropped {drop * 100:.0f}pp "
                    f"({(base.keyword_coverage or 0) * 100:.0f}% → "
                    f"{(cur.keyword_coverage or 0) * 100:.0f}%)"
                ),
                detail=(
                    f"Median keyword coverage on the substantive answer "
                    f"dropped from {(base.keyword_coverage or 0):.2f} to "
                    f"{(cur.keyword_coverage or 0):.2f}."
                ),
            ))

        if cur.red_flag and not base.red_flag:
            flags.append(CanaryDriftFlag(
                question=question, kind="red_flag_emerged", severity="major",
                headline="Fabrication red flag emerged",
                detail=(
                    f"Canary {question!r} now generates a `must_not_appear` "
                    f"phrase that was absent on baseline."
                ),
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
    """Drift counts grouped by expected_outcome + by category + by drift kind
    — chips above the per-flag cards in the canary panel. Pre-#45 the
    `by_branch` group keyed on `expected_branch`; the new contract groups
    by outcome instead."""
    by_question = {q.question: q for q in corpus}
    by_outcome: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    by_drift_kind: Counter[str] = Counter()
    for f in flags:
        by_drift_kind[f.kind] += 1
        q = by_question.get(f.question)
        if q is None:
            continue
        by_outcome[q.expected_outcome] += 1
        by_category[q.category] += 1
    return {
        "by_outcome": dict(by_outcome),
        "by_category": dict(by_category),
        "by_drift_kind": dict(by_drift_kind),
    }

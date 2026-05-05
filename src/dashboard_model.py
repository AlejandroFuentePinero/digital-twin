"""Pure aggregations over interaction records — Sentinel's deep model (issue #29).

No I/O. Construct from a list of `InteractionRecord` (typically supplied by
`log_reader.LocalReader`) and read precomputed metrics off the instance. The
Sentinel UI in `sentinel.py` is the only consumer.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median, quantiles
from typing import Callable

from interaction_log import InteractionRecord

# Mirror of pipeline.MAX_ATTEMPTS — kept local to avoid pulling pipeline.py's
# heavy import surface (subprocess, classifier, generator, etc.) into the pure
# dashboard model. If pipeline's value changes, update here.
MAX_ATTEMPTS = 3
LOW_CONFIDENCE_THRESHOLD = 0.7
HIGH_CONFIDENCE_THRESHOLD = 0.8


@dataclass(frozen=True)
class DashboardModel:
    records: list[InteractionRecord]
    # Cross-reference set of session IDs that submitted contact info via
    # `contacts.jsonl`. Required because the live pipeline writer sets
    # `contact_provided=True` on the InteractionRecord *after* the form
    # submit, so the same record never carries both `contact_offered=True`
    # and `contact_provided=True` — record-level intersection returns 0%
    # even when the form *was* converted. Joining on `session_id` gives the
    # true conversion. Empty default preserves the legacy record-level
    # signal for callers that don't load the contact log.
    provided_session_ids: frozenset[str] = field(default_factory=frozenset)
    # Canary filtering (issue #39). Default is "live tabs only" — every Metrics
    # / Trends / Failures consumer constructs `DashboardModel(records)` and
    # never sees canary records. The Canary tab opts in via
    # `DashboardModel(records, include_canary=True, only_canary=True)`.
    include_canary: bool = False
    only_canary: bool = False

    def __post_init__(self) -> None:
        if self.only_canary:
            kept = [r for r in self.records if r.is_canary]
        elif self.include_canary:
            kept = list(self.records)
        else:
            kept = [r for r in self.records if not r.is_canary]
        # frozen dataclass — assign through object.__setattr__
        object.__setattr__(self, "records", kept)

    @property
    def total_interactions(self) -> int:
        return len(self.records)

    @property
    def gap_rate(self) -> float:
        # Direct read of the producer-emitted signal post-#42 (PRD #41 slice 1).
        # The pre-#42 ``or not r.knew_answer`` proxy is gone — the producer now
        # emits all four EventType values, and LogReader smart-normalizes
        # pre-v4 records carrying GAP_PHRASE.
        return self._rate_of(lambda r: r.event_type == "gap")

    @property
    def deflection_rate(self) -> float:
        return self._rate_of(lambda r: r.event_type == "deflected")

    @property
    def refusal_rate(self) -> float:
        return self._rate_of(lambda r: r.event_type == "refused")

    @property
    def retry_exhausted_rate(self) -> float:
        return self._rate_of(lambda r: len(r.attempts) >= MAX_ATTEMPTS)

    @property
    def guardrail_rejection_rate(self) -> float:
        return self._rate_of(
            lambda r: any(not a.get("is_acceptable", True) for a in r.attempts)
        )

    @property
    def latency_p50(self) -> float | None:
        return self._percentile(50)

    @property
    def latency_p95(self) -> float | None:
        return self._percentile(95)

    def _percentile(self, pct: int, stage: str = "total") -> float | None:
        latencies = [r.latency_ms.get(stage, 0) for r in self.records]
        if not latencies:
            return None
        if len(latencies) == 1:
            return float(latencies[0])
        # statistics.quantiles uses inclusive linear interpolation when method="inclusive";
        # n=100 gives one cut point per percentile, so cuts[pct-1] is the pct-th percentile.
        cuts = quantiles(latencies, n=100, method="inclusive")
        return cuts[pct - 1]

    def latency_percentiles(
        self, stage: str, percentiles: tuple[int, ...] = (50, 95)
    ) -> dict[int, float | None]:
        """Per-stage percentile dict. Stage ∈ {classifier, retrieval, generation,
        guardrail, total}. Returns {pct: value | None} so the UI can render a
        full row even when no data is available."""
        return {pct: self._percentile(pct, stage=stage) for pct in percentiles}

    def latency_with_share(self, stage: str) -> dict[str, float | None]:
        """Per-stage p50 + p95 + share-of-total-p95.

        Share = stage_p95 / total_p95, expressed as a fraction. Surfaces which
        stage drives the headline latency tail — typical "guardrail consumes
        50% of total p95" pattern is the canonical drift signal here."""
        pcts = self.latency_percentiles(stage)
        total_p95 = self._percentile(95, stage="total")
        share: float | None
        if pcts.get(95) is None or total_p95 is None or total_p95 == 0:
            share = None
        else:
            share = pcts[95] / total_p95
        return {"p50": pcts.get(50), "p95": pcts.get(95), "share": share}

    @property
    def attempts_distribution(self) -> dict[str, float]:
        """Share of turns by attempt count: ``{"1": 0.75, "2": 0.18, "3": 0.07}``.

        Bucket keys are exact counts because ``pipeline.MAX_ATTEMPTS = 3`` is
        the hard upper bound (the guardrail loop terminates at attempt 3); a
        ``"3+"`` label would suggest a "4 or more" possibility that doesn't
        exist. If MAX_ATTEMPTS ever rises, generalise the bucket keys to
        match.

        Surfaces what fraction of turns the guardrail had to push back on. The
        endpoints are already covered by ``refusal_rate`` / ``retry_exhausted_rate``;
        this fills in the middle (turns that recovered on attempt 2)."""
        if not self.records:
            return {}
        total = len(self.records)
        buckets = {"1": 0, "2": 0, "3": 0}
        for r in self.records:
            n = len(r.attempts)
            if n <= 1:
                buckets["1"] += 1
            elif n == 2:
                buckets["2"] += 1
            else:
                buckets["3"] += 1
        return {k: v / total for k, v in buckets.items()}

    @property
    def event_counts(self) -> dict[str, int]:
        return dict(Counter(r.event_type for r in self.records))

    @property
    def branch_counts(self) -> dict[str, int]:
        return dict(Counter(r.branch for r in self.records))

    def low_confidence_rate(self, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> float:
        return self._rate_of(lambda r: r.classification_confidence < threshold)

    @property
    def mean_classification_confidence(self) -> float | None:
        """Mean classifier confidence across all records, or None if empty.

        Direct read of how sure the classifier is on average — sits alongside
        the rate-style ``low_confidence_rate`` and ``confident_failure_rate``
        in the Routing block."""
        if not self.records:
            return None
        return sum(r.classification_confidence for r in self.records) / len(self.records)

    @property
    def unique_sessions(self) -> int:
        return len({r.session_id for r in self.records})

    @property
    def turns_per_session_median(self) -> float | None:
        if not self.records:
            return None
        return median(Counter(r.session_id for r in self.records).values())

    @property
    def mean_turns_per_session(self) -> float | None:
        """Mean turns per session — direct read of "average questions asked
        per session". Operator-friendly companion to the median."""
        if not self.records:
            return None
        sessions = Counter(r.session_id for r in self.records)
        return sum(sessions.values()) / len(sessions)

    @property
    def dropoff_by_turn(self) -> dict[int, int]:
        return dict(Counter(r.turn_index for r in self.records))

    @property
    def contact_offer_rate(self) -> float:
        return self._rate_of(lambda r: r.contact_offered)

    @property
    def contact_conversion_rate(self) -> float | None:
        """Sessions that converted ÷ sessions that were offered the form.

        Counts a session as converted when *either* an in-log record carries
        `contact_provided=True` OR the session_id appears in the cross-
        referenced `provided_session_ids` from contacts.jsonl. The
        cross-reference is the load-bearing signal in production — the
        in-log signal is a fallback for tests / synthetic data."""
        sessions_offered = {r.session_id for r in self.records if r.contact_offered}
        if not sessions_offered:
            return None
        sessions_provided_in_log = {r.session_id for r in self.records if r.contact_provided}
        sessions_provided = sessions_provided_in_log | self.provided_session_ids
        return len(sessions_offered & sessions_provided) / len(sessions_offered)

    @property
    def technical_tool_call_rate(self) -> float | None:
        """Share of TECHNICAL turns that invoked at least one tool call.

        Descriptive — direction-of-change orientation, not a target. Pre-#42
        was named ``technical_tool_uptake_rate``; "uptake" implied a target the
        system isn't trying to hit (PRD #41 slice 3). Denominator is "all
        TECHNICAL", not "TECHNICAL warranting a tool" — see LIMITATIONS::P8.
        """
        technical = [r for r in self.records if r.branch == "TECHNICAL"]
        if not technical:
            return None
        return sum(1 for r in technical if r.tool_calls) / len(technical)

    def outcome_accuracy(self, corpus) -> float | None:
        """Fraction of canary records whose derived outcome matches the corpus's
        ``expected_outcome`` for the same question text. Headline correctness
        signal post-#45; replaces the pre-#45 ``branch_match_rate`` (which
        asserted mechanism — which branch fired — instead of outcome quality)."""
        from canary_outcome import derive_outcome
        by_question = {q.question: q for q in corpus}
        relevant = [r for r in self.records if r.question in by_question]
        if not relevant:
            return None
        hits = sum(
            1 for r in relevant
            if derive_outcome(r, by_question[r.question]) == by_question[r.question].expected_outcome
        )
        return hits / len(relevant)

    def keyword_coverage(self, corpus) -> float | None:
        """Mean per-record keyword coverage across canary records whose corpus
        question carries ``expected_outcome=='answered_with_substance'`` AND
        a non-empty ``expected_keywords`` list. Skips other outcomes — a
        gap-acknowledgement doesn't need keyword coverage; the gap-phrase
        contract gates correctness via ``derive_outcome`` instead."""
        from canary_outcome import keyword_hits
        by_question = {q.question: q for q in corpus}
        scores: list[float] = []
        for r in self.records:
            q = by_question.get(r.question)
            if q is None:
                continue
            if q.expected_outcome != "answered_with_substance":
                continue
            matched, total = keyword_hits(r, q)
            if total == 0:
                continue
            scores.append(matched / total)
        if not scores:
            return None
        return sum(scores) / len(scores)

    def red_flag_rate(self, corpus) -> float | None:
        """Fraction of canary records whose answer text contains any
        per-question ``must_not_appear`` substring. Fabrication-detection
        signal post-#45 — populated for gap / refused / out-of-scope corpus
        entries (and for substantive entries where a specific shape would
        constitute fabrication)."""
        from canary_outcome import has_red_flag
        by_question = {q.question: q for q in corpus}
        relevant = [r for r in self.records if r.question in by_question]
        if not relevant:
            return None
        hits = sum(1 for r in relevant if has_red_flag(r, by_question[r.question]))
        return hits / len(relevant)

    @property
    def tool_call_count(self) -> int:
        """Total number of tool invocations across all records — volume signal
        in the Tool use block. Pairs with ``technical_tool_call_rate``
        (rate) and ``tool_call_success_rate`` (quality)."""
        return sum(len(r.tool_calls) for r in self.records)

    @property
    def tool_call_success_rate(self) -> float | None:
        all_calls = [c for r in self.records for c in r.tool_calls]
        if not all_calls:
            return None
        return sum(1 for c in all_calls if c.get("status") == "success") / len(all_calls)

    @property
    def answered_with_substance_rate(self) -> float:
        """Share of turns the producer classified as a substantive answer.
        Completes the 4-bucket Outcome partition: gap + deflected + refused
        + answered_with_substance = 100%. Tier B per the post-#48 framework
        — shift-detected, not threshold-alerted (substance share is shape,
        not health)."""
        return self._rate_of(lambda r: r.event_type == "answered")

    @property
    def mean_confidence_by_branch(self) -> dict[str, float]:
        """Mean classifier confidence per branch — the actionable Routing
        breakdown. Today only the global mean (`mean_classification_confidence`)
        is surfaced; per-branch lets the operator scan which branch the
        classifier is wobbling on. Renders as a one-row chip in the Metrics
        tab Routing block, mirroring the `branch_distribution` shape."""
        from collections import defaultdict
        by_branch: dict[str, list[float]] = defaultdict(list)
        for r in self.records:
            by_branch[r.branch].append(r.classification_confidence)
        return {
            branch: sum(confs) / len(confs)
            for branch, confs in by_branch.items()
            if confs
        }

    @property
    def branch_distribution(self) -> dict[str, float]:
        if not self.records:
            return {}
        total = len(self.records)
        return {branch: count / total for branch, count in self.branch_counts.items()}

    def _rate_of(self, predicate) -> float:
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if predicate(r)) / len(self.records)

    def for_window(self, days: int | None) -> "DashboardModel":
        if days is None:
            return self
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        # `self.records` has already been canary-filtered in __post_init__;
        # pass include_canary=True so the child doesn't re-filter and
        # accidentally drop canaries when the parent is only_canary.
        return DashboardModel(
            [r for r in self.records if r.timestamp >= cutoff],
            provided_session_ids=self.provided_session_ids,
            include_canary=True,
        )

    def time_series_by_day(
        self, metric: str, days: int | None
    ) -> list[tuple[date, float | None]]:
        """Daily values for a thresholded metric (see METRIC_GETTERS).

        Returns one ``(utc_date, value)`` per day. Days with no records report ``None``
        — rendered as gaps in the line chart, not zeros. Empty record set → ``[]`` so the
        chart layer can show an "insufficient data" placeholder.

        ``days=N`` covers the trailing window ending today (UTC). ``days=None`` spans
        the data's full date range (earliest record → today).
        """
        if not self.records:
            return []
        getter = METRIC_GETTERS[metric]
        by_day: dict[date, list[InteractionRecord]] = defaultdict(list)
        for r in self.records:
            by_day[_record_date(r)].append(r)

        today = datetime.now(timezone.utc).date()
        if days is None:
            start = min(by_day.keys())
            span = (today - start).days + 1
        else:
            span = days
            start = today - timedelta(days=span - 1)

        return [
            (
                start + timedelta(days=offset),
                getter(DashboardModel(by_day[start + timedelta(days=offset)]))
                if (start + timedelta(days=offset)) in by_day else None,
            )
            for offset in range(span)
        ]

    def for_prior_window(self, days: int | None) -> "DashboardModel":
        """Records from the window immediately preceding `for_window(days)`.

        for_prior_window(7) → records timestamped between (now - 14d) and
        (now - 7d). Drives week-over-week deltas in Sentinel (issue #36).
        Returns an empty model for `days=None` (Global has no prior).
        """
        if days is None:
            return DashboardModel([])
        now = datetime.now(timezone.utc)
        prior_start = (now - timedelta(days=2 * days)).isoformat()
        prior_end = (now - timedelta(days=days)).isoformat()
        return DashboardModel(
            [r for r in self.records if prior_start <= r.timestamp < prior_end],
            provided_session_ids=self.provided_session_ids,
            include_canary=True,
        )


def _record_date(record: InteractionRecord) -> date:
    """UTC calendar date for a record's timestamp (ISO-8601 string)."""
    return datetime.fromisoformat(record.timestamp).astimezone(timezone.utc).date()


# Registry of plottable metrics — every key in `metric_status.THRESHOLDS` (issue #36)
# needs a getter here so `time_series_by_day` and the Trend Explorer (issue #30) can
# compute it per day. Keep in sync with THRESHOLDS; tests pin both keysets together.
METRIC_GETTERS: dict[str, Callable[["DashboardModel"], float | None]] = {
    # Outcome
    "gap_rate": lambda m: m.gap_rate,
    "deflection_rate": lambda m: m.deflection_rate,
    "refusal_rate": lambda m: m.refusal_rate,
    "guardrail_rejection_rate": lambda m: m.guardrail_rejection_rate,
    "retry_exhausted_rate": lambda m: m.retry_exhausted_rate,
    "answered_with_substance_rate": lambda m: m.answered_with_substance_rate,
    # Routing
    "low_confidence_rate": lambda m: m.low_confidence_rate(),
    "mean_classification_confidence": lambda m: m.mean_classification_confidence,
    # Engagement
    "turns_per_session_median": lambda m: m.turns_per_session_median,
    "mean_turns_per_session": lambda m: m.mean_turns_per_session,
    "contact_offer_rate": lambda m: m.contact_offer_rate,
    "contact_conversion_rate": lambda m: m.contact_conversion_rate,
    # Tool use
    "technical_tool_call_rate": lambda m: m.technical_tool_call_rate,
    "tool_call_success_rate": lambda m: m.tool_call_success_rate,
    # Latency
    "latency_p95_total": lambda m: m.latency_percentiles("total").get(95),
}

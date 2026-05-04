"""Pure aggregations over interaction records — Sentinel's deep model (issue #29).

No I/O. Construct from a list of `InteractionRecord` (typically supplied by
`log_reader.LocalReader`) and read precomputed metrics off the instance. The
Sentinel UI in `sentinel.py` is the only consumer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median, quantiles

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

    @property
    def total_interactions(self) -> int:
        return len(self.records)

    @property
    def gap_rate(self) -> float:
        # Union of the *intended* gap signal (event_type=='gap') with the
        # *actual* gap signal in live data (knew_answer=False). Live-log
        # inventory found 0/85 records ever stamped event_type=='gap', but
        # 8/85 carry knew_answer=False — pipeline writer bug, ticketed
        # separately. Until that's fixed, both surfaces are gap evidence.
        return self._rate_of(lambda r: r.event_type == "gap" or not r.knew_answer)

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

    @property
    def event_counts(self) -> dict[str, int]:
        return dict(Counter(r.event_type for r in self.records))

    @property
    def branch_counts(self) -> dict[str, int]:
        return dict(Counter(r.branch for r in self.records))

    def low_confidence_rate(self, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> float:
        return self._rate_of(lambda r: r.classification_confidence < threshold)

    @property
    def unique_sessions(self) -> int:
        return len({r.session_id for r in self.records})

    @property
    def turns_per_session_median(self) -> float | None:
        if not self.records:
            return None
        return median(Counter(r.session_id for r in self.records).values())

    @property
    def dropoff_by_turn(self) -> dict[int, int]:
        return dict(Counter(r.turn_index for r in self.records))

    @property
    def contact_offer_rate(self) -> float:
        return self._rate_of(lambda r: r.contact_offered)

    @property
    def contact_conversion_rate(self) -> float | None:
        offered = [r for r in self.records if r.contact_offered]
        if not offered:
            return None
        return sum(1 for r in offered if r.contact_provided) / len(offered)

    @property
    def technical_tool_uptake_rate(self) -> float | None:
        technical = [r for r in self.records if r.branch == "TECHNICAL"]
        if not technical:
            return None
        return sum(1 for r in technical if r.tool_calls) / len(technical)

    @property
    def tool_call_success_rate(self) -> float | None:
        all_calls = [c for r in self.records for c in r.tool_calls]
        if not all_calls:
            return None
        return sum(1 for c in all_calls if c.get("status") == "success") / len(all_calls)

    @property
    def multi_label_rate(self) -> float | None:
        # Live data: 0/79 records have len(classifier_labels) > 1 — composition
        # routing dormant in practice (ADR-0003 § Composition table). None when
        # the corpus has zero populated labels (e.g. all-legacy-v1).
        populated = [r for r in self.records if r.classifier_labels]
        if not populated:
            return None
        return sum(1 for r in populated if len(r.classifier_labels) > 1) / len(populated)

    def confident_failure_rate(self, threshold: float = HIGH_CONFIDENCE_THRESHOLD) -> float:
        # Surfaces the failures `low_confidence_rate` is blind to: the
        # classifier was sure, but the turn still failed. A failure here is
        # any of (gap | retry | refusal). Issue #35 'Detection gap'.
        def _failed(r: InteractionRecord) -> bool:
            return (
                not r.knew_answer
                or any(not a.get("is_acceptable", True) for a in r.attempts)
                or r.event_type == "refused"
            )
        return self._rate_of(lambda r: r.classification_confidence >= threshold and _failed(r))

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
        return DashboardModel([r for r in self.records if r.timestamp >= cutoff])

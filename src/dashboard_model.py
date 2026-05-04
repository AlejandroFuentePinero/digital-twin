"""Pure aggregations over interaction records — Sentinel's deep model (issue #29).

No I/O. Construct from a list of `InteractionRecord` (typically supplied by
`log_reader.LocalReader`) and read precomputed metrics off the instance. The
Sentinel UI in `sentinel.py` is the only consumer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import quantiles

from interaction_log import InteractionRecord


@dataclass(frozen=True)
class DashboardModel:
    records: list[InteractionRecord]

    @property
    def total_interactions(self) -> int:
        return len(self.records)

    @property
    def gap_rate(self) -> float:
        return self._rate_of(lambda r: r.event_type == "gap")

    @property
    def deflection_rate(self) -> float:
        return self._rate_of(lambda r: r.event_type == "deflected")

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

    def _percentile(self, pct: int) -> float | None:
        latencies = [r.latency_ms.get("total", 0) for r in self.records]
        if not latencies:
            return None
        if len(latencies) == 1:
            return float(latencies[0])
        # statistics.quantiles uses inclusive linear interpolation when method="inclusive";
        # n=100 gives one cut point per percentile, so cuts[pct-1] is the pct-th percentile.
        cuts = quantiles(latencies, n=100, method="inclusive")
        return cuts[pct - 1]

    @property
    def event_counts(self) -> dict[str, int]:
        return dict(Counter(r.event_type for r in self.records))

    def _rate_of(self, predicate) -> float:
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if predicate(r)) / len(self.records)

    def for_window(self, days: int) -> "DashboardModel":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return DashboardModel([r for r in self.records if r.timestamp >= cutoff])

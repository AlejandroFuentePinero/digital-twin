"""Failure-feed pure logic — Sentinel's per-turn debugging surface (issue #31).

Three pure functions over `InteractionRecord` lists. The Sentinel UI in
`sentinel.py` is the only consumer; no I/O, no Gradio. Mirrors the sibling-
module pattern of `metric_status.py` so `dashboard_model.py` stays focused on
metric aggregations.

`classify_failure` assigns a single failure-mode label per record (or None);
`select_failures` filters + truncates + orders for the dataframe view;
`group_by_session` builds per-session aggregates for the "View full session" view.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from dashboard_model import MAX_ATTEMPTS
from interaction_log import InteractionRecord

# Truncate the question column to keep the dataframe row scannable. Full text
# is always available in the per-turn drilldown via `record.question`.
QUESTION_PREVIEW_CHARS = 80


@dataclass(frozen=True)
class FailureRow:
    """One row in the Failure Feed dataframe + its source record for drilldown."""
    timestamp: str
    branch: str
    failure_mode: str
    question: str
    attempt_count: int
    classification_confidence: float
    record: InteractionRecord

# Mutually-exclusive failure labels. Precedence (highest first): the most
# severe / earliest-terminating outcome wins, so the failure-mode dropdown
# can filter on a single label per row without double counting.
FAILURE_MODES = (
    "refused", "gap", "deflected", "retry-exhausted", "rejected-then-recovered"
)


# Plain-English labels for the Failure Feed accordion summary + dropdown.
# Honest about the outcome — `gap` and `deflected` are informational
# (correct system behaviour, useful to surface for pattern-spotting).
FAILURE_MODE_LABELS: dict[str, str] = {
    "refused":                  "refused (no answer)",
    "gap":                      "gap (couldn't answer)",
    "deflected":                "deflected (out-of-scope redirect)",
    "retry-exhausted":          "retry exhausted (3+ attempts rejected)",
    "rejected-then-recovered":  "rejected then recovered (is_acceptable=false on early attempt)",
}


# Per-mode CSS class, drives the row stripe + summary count colour. Each
# mode gets a distinct colour so the operator can differentiate at a glance.
# (Older code referenced this as ``FAILURE_MODE_SEVERITY``; the rename here
# reflects that we no longer collapse modes into a 3-bucket severity.)
FAILURE_MODE_SEVERITY: dict[str, str] = {
    "refused":                  "refused",
    "retry-exhausted":          "retry-exhausted",
    "rejected-then-recovered":  "rejected-then-recovered",
    "gap":                      "gap",
    "deflected":                "deflected",
}

# Sort rank: refused first (system gave up), retry-exhausted next (3
# rejected attempts), rejected-then-recovered (system fought back to OK),
# gap and deflected last (informational — honest "I don't know" or correct
# out-of-scope redirect, surfaced for pattern-spotting not as defects).
_SEVERITY_RANK: dict[str, int] = {
    "refused":                  0,
    "retry-exhausted":          1,
    "rejected-then-recovered":  2,
    "gap":                      3,
    "deflected":                4,
}


def failure_mode_counts(records: list[InteractionRecord]) -> dict[str, int]:
    """Per-mode count over ``records``. Surfaces the per-mode breakdown above
    the feed so the operator sees the distribution at a glance ('17 failures
    · 8 unknown answer · 5 rejected then recovered · 1 retry exhausted · 1
    refused')."""
    counts: dict[str, int] = {mode: 0 for mode in FAILURE_MODES}
    for r in records:
        mode = classify_failure(r)
        if mode is not None:
            counts[mode] = counts.get(mode, 0) + 1
    return counts


def sort_feed(rows: "list[FailureRow]") -> "list[FailureRow]":
    """Severity-then-recency sort used by the Failure Feed view.

    Two-pass stable sort: first by recency descending (so within each band
    the newest row sits at the top), then by severity ascending (alerts →
    warnings → muted). Python's ``sort`` is stable so the recency order
    survives within each severity band."""
    by_recency = sorted(rows, key=lambda r: r.timestamp, reverse=True)
    return sorted(
        by_recency,
        key=lambda r: _SEVERITY_RANK.get(r.failure_mode, 99),
    )


def classify_failure(record: InteractionRecord) -> str | None:
    """Return a failure-mode label for the record, or None if it isn't a failure.

    Post-#43 the contract reads ``event_type`` directly — the legacy
    ``not knew_answer`` proxy is gone. ``deflected`` is treated as the
    lowest-severity informational mode (see slice-2 audit § 2)."""
    if record.event_type == "refused":
        return "refused"
    if record.event_type == "gap":
        return "gap"
    if record.event_type == "deflected":
        return "deflected"
    rejected = any(not a.get("is_acceptable", True) for a in record.attempts)
    if not rejected:
        return None
    if len(record.attempts) >= MAX_ATTEMPTS:
        return "retry-exhausted"
    return "rejected-then-recovered"


def _truncate(question: str) -> str:
    if len(question) <= QUESTION_PREVIEW_CHARS:
        return question
    return question[: QUESTION_PREVIEW_CHARS - 1].rstrip() + "…"


def select_failures(
    records: list[InteractionRecord],
    *,
    branch: str = "All",
    failure_mode: str = "All",
    question_search: str = "",
) -> list[FailureRow]:
    """Filter, label, and pack records into FailureRow form.

    Filters apply with AND semantics; `"All"` is the wildcard for `branch` and
    `failure_mode`. `question_search` is a case-insensitive substring match on the
    full question; the empty string is a no-op.
    """
    needle = question_search.lower()
    rows: list[FailureRow] = []
    for r in records:
        mode = classify_failure(r)
        if mode is None:
            continue
        if branch != "All" and r.branch != branch:
            continue
        if failure_mode != "All" and mode != failure_mode:
            continue
        if needle and needle not in r.question.lower():
            continue
        rows.append(
            FailureRow(
                timestamp=r.timestamp,
                branch=r.branch,
                failure_mode=mode,
                question=_truncate(r.question),
                attempt_count=len(r.attempts),
                classification_confidence=r.classification_confidence,
                record=r,
            )
        )
    return sort_feed(rows)


@dataclass(frozen=True)
class Session:
    """All turns for one session_id, ordered by turn_index ascending."""
    session_id: str
    records: list[InteractionRecord]

    @property
    def turn_count(self) -> int:
        return len(self.records)

    @property
    def contact_offered(self) -> bool:
        return any(r.contact_offered for r in self.records)

    @property
    def contact_provided(self) -> bool:
        return any(r.contact_provided for r in self.records)

    @property
    def total_latency_ms(self) -> int:
        return sum(r.latency_ms.get("total", 0) for r in self.records)


def group_by_session(records: list[InteractionRecord]) -> list[Session]:
    """Group records by session_id; within each session, sort turns by turn_index."""
    by_session: dict[str, list[InteractionRecord]] = defaultdict(list)
    for r in records:
        by_session[r.session_id].append(r)
    return [
        Session(session_id=sid, records=sorted(rs, key=lambda r: r.turn_index))
        for sid, rs in by_session.items()
    ]

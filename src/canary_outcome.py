"""Canary outcome derivation — pure functions over (record, corpus question).

Canary-side counterpart to slice 1's `event_classifier` deep module. Maps the
producer-emitted `event_type` (post-#42 contract: answered | gap | deflected |
refused) onto one of four outcome buckets the canary surface measures:

- ``answered_with_substance`` — substantive KB-grounded response.
- ``gap_acknowledged``        — system honestly said it didn't have the info.
- ``out_of_scope_redirect``   — polite redirect on out-of-scope (trivia, opinions).
- ``refused``                 — guardrail-rejected every attempt.

`derive_outcome` is intentionally a thin adapter over `record.event_type` —
the producer's `event_classifier` already collapses (branch + last_answer) into
the four event_type values, so this module reads that signal directly without
re-implementing the rule.

Two companion functions read the corpus side of the contract:

- `has_red_flag(record, question)` — fabrication detection. Any ``must_not_appear``
  substring in any attempt's answer text → True. Scans every attempt (not just
  the last accepted one) so guardrail-caught fabrications still count.
- `keyword_hits(record, question)` — (matched, total) for ``expected_keywords``.
  Substring + case-insensitive. The dashboard aggregates these into
  ``keyword_coverage(corpus)``.

No I/O, no side effects. Tested directly in `tests/test_canary_outcome.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from interaction_log import InteractionRecord

if TYPE_CHECKING:
    from canary_corpus import CanaryQuestion

Outcome = Literal[
    "answered_with_substance",
    "gap_acknowledged",
    "out_of_scope_redirect",
    "refused",
]


def derive_outcome(record: InteractionRecord, question: CanaryQuestion) -> Outcome:
    """Map a record's `event_type` to one of the four outcome buckets.

    Pure adapter: the producer's `event_classifier` already did the hard work
    of choosing event_type from (branch, final_answer, GAP_PHRASE,
    DEFLECTION_MARKERS). This function just renames it into the canary's
    quality contract."""
    event_type = record.event_type
    if event_type == "refused":
        return "refused"
    if event_type == "gap":
        return "gap_acknowledged"
    if event_type == "deflected":
        return "out_of_scope_redirect"
    return "answered_with_substance"


def has_red_flag(record: InteractionRecord, question: CanaryQuestion) -> bool:
    """True if any ``must_not_appear`` substring appears in any attempt's
    answer text. Case-insensitive substring match.

    Scans every attempt — fabrications caught and corrected by the guardrail
    still count, because the metric measures whether the system *generated*
    the forbidden shape, not whether the user saw it."""
    if not question.must_not_appear:
        return False
    haystacks = [
        (attempt.get("answer") or "").lower() for attempt in record.attempts
    ]
    needles = [phrase.lower() for phrase in question.must_not_appear]
    return any(needle in hay for hay in haystacks for needle in needles)


def keyword_hits(
    record: InteractionRecord, question: CanaryQuestion
) -> tuple[int, int]:
    """Return ``(matched, total)`` for ``question.expected_keywords`` against
    the union of every attempt's answer text. Case-insensitive substring.

    Returns ``(0, 0)`` when ``expected_keywords`` is empty — the dashboard's
    aggregator skips zero-total questions when computing coverage."""
    keywords = question.expected_keywords
    if not keywords:
        return (0, 0)
    haystack = " ".join(
        (attempt.get("answer") or "") for attempt in record.attempts
    ).lower()
    matched = sum(1 for kw in keywords if kw.lower() in haystack)
    return (matched, len(keywords))

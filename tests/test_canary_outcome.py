"""Tests for the canary outcome deep module (PRD #41 / #45).

`canary_outcome.py` is the canary-side counterpart to slice 1's `event_classifier`:
a pure function over (record, corpus_question) that derives one of four outcome
buckets — answered_with_substance | gap_acknowledged | out_of_scope_redirect |
refused. The dashboard's outcome metrics + drift detector's outcome_changed
flag both read this function. No I/O, no mocks needed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from canary_corpus import CanaryQuestion
from canary_outcome import (
    derive_outcome,
    has_red_flag,
    keyword_hits,
)
from interaction_log import InteractionRecord


def _r(
    *,
    event_type: str = "answered",
    attempts: list[dict] | None = None,
    branch: str = "TECHNICAL",
    question: str = "q1",
) -> InteractionRecord:
    if attempts is None:
        attempts = [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}]
    return InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "canary",
        "turn_index": 0,
        "question": question,
        "event_type": event_type,
        "branch": branch,
        "classification_confidence": 0.9,
        "attempts": attempts,
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0,
                       "guardrail": 0, "total": 1000},
        "knew_answer": True,
        "is_canary": True,
    })


def _q(
    *,
    expected_outcome: str = "answered_with_substance",
    expected_keywords: list[str] | None = None,
    must_not_appear: list[str] | None = None,
    question: str = "q1",
) -> CanaryQuestion:
    return CanaryQuestion(
        id="C001",
        question=question,
        expected_outcome=expected_outcome,
        expected_keywords=list(expected_keywords or []),
        must_not_appear=list(must_not_appear or []),
        expected_chunk_sources=[],
        category="x",
    )


# ----- derive_outcome --------------------------------------------------------


def test_derive_outcome_returns_refused_for_refused_event_type():
    """event_type='refused' → outcome='refused'. The producer's refused token
    is the deepest negative signal; nothing else can override it."""
    record = _r(event_type="refused")
    question = _q(expected_outcome="refused")
    assert derive_outcome(record, question) == "refused"


def test_derive_outcome_returns_gap_acknowledged_for_gap_event_type():
    """event_type='gap' → outcome='gap_acknowledged'. Whether the system
    answered via the canonical gap phrase or via a constructive GAP-branch
    response, the producer's `gap` token is the contract."""
    record = _r(event_type="gap")
    question = _q(expected_outcome="gap_acknowledged")
    assert derive_outcome(record, question) == "gap_acknowledged"


def test_derive_outcome_returns_out_of_scope_redirect_for_deflected_event_type():
    """event_type='deflected' → outcome='out_of_scope_redirect'. Polite
    redirect on out-of-scope (trivia, opinions) is the correct outcome shape;
    the producer emits it for LOGISTICAL turns + non-LOGISTICAL turns whose
    answer carries a DEFLECTION_MARKERS phrase."""
    record = _r(event_type="deflected")
    question = _q(expected_outcome="out_of_scope_redirect")
    assert derive_outcome(record, question) == "out_of_scope_redirect"


def test_derive_outcome_returns_answered_with_substance_for_answered_event_type():
    """event_type='answered' → outcome='answered_with_substance'. The
    correctness of substance is judged by `keyword_coverage` separately;
    `derive_outcome` only maps the producer signal to the bucket."""
    record = _r(event_type="answered")
    question = _q(expected_outcome="answered_with_substance")
    assert derive_outcome(record, question) == "answered_with_substance"


# ----- has_red_flag ----------------------------------------------------------


def test_has_red_flag_returns_true_when_must_not_appear_substring_present():
    """Fabrication detection: if any `must_not_appear` substring appears in
    any attempt's answer text, the question's red-flag fires. C006 (kdb+/q
    gap) shape: corpus says 'must_not_appear=["I have used kdb"]'; answer
    contains the phrase → red flag."""
    record = _r(attempts=[
        {"answer": "Yes, I have used kdb+/q at scale.",
         "is_acceptable": True, "guardrail_feedback": ""}
    ])
    question = _q(must_not_appear=["I have used kdb"])
    assert has_red_flag(record, question) is True


def test_has_red_flag_returns_false_when_must_not_appear_empty():
    """Most `answered_with_substance` corpus entries have no `must_not_appear`
    phrases (no obvious fabrication shape). Empty list → never fires."""
    record = _r(attempts=[
        {"answer": "Anything goes here.", "is_acceptable": True,
         "guardrail_feedback": ""}
    ])
    question = _q(must_not_appear=[])
    assert has_red_flag(record, question) is False


def test_has_red_flag_is_case_insensitive():
    """`must_not_appear` is operator-edited; case sensitivity would force the
    operator to enumerate every casing. Match case-insensitively so the
    contract is robust to model-output capitalisation."""
    record = _r(attempts=[
        {"answer": "I HAVE USED KDB+/Q in production.",
         "is_acceptable": True, "guardrail_feedback": ""}
    ])
    question = _q(must_not_appear=["i have used kdb"])
    assert has_red_flag(record, question) is True


def test_has_red_flag_scans_all_attempts_not_just_last():
    """Fabrication caught and corrected by the guardrail still counts as a
    red flag — the model produced the fabrication once. The metric measures
    whether the system *generated* the must_not_appear shape, not whether the
    user saw it. Reading only the last accepted attempt would mask this."""
    record = _r(attempts=[
        {"answer": "I have used kdb+/q for years.",
         "is_acceptable": False, "guardrail_feedback": "fabrication"},
        {"answer": "I don't have hands-on with kdb+/q.",
         "is_acceptable": True, "guardrail_feedback": ""},
    ])
    question = _q(must_not_appear=["I have used kdb"])
    assert has_red_flag(record, question) is True


# ----- keyword_hits ----------------------------------------------------------


def test_keyword_hits_returns_matched_and_total_counts():
    """(matched, total) — the dashboard aggregates these across records to
    compute `keyword_coverage`. Matching is substring-based, case-insensitive."""
    record = _r(attempts=[
        {"answer": "Final ensemble achieved MAE 29.95 and R² 86.3.",
         "is_acceptable": True, "guardrail_feedback": ""}
    ])
    question = _q(expected_keywords=["MAE", "29.95", "R²", "86.3"])
    matched, total = keyword_hits(record, question)
    assert matched == 4
    assert total == 4


def test_keyword_hits_is_case_insensitive():
    """Same rationale as has_red_flag — substring match shouldn't force the
    operator to enumerate casings."""
    record = _r(attempts=[
        {"answer": "uses bayesian hierarchical modelling on 33 iterations.",
         "is_acceptable": True, "guardrail_feedback": ""}
    ])
    question = _q(expected_keywords=["Bayesian hierarchical", "33"])
    matched, total = keyword_hits(record, question)
    assert matched == 2
    assert total == 2


def test_keyword_hits_returns_partial_count_when_some_keywords_missing():
    """Partial coverage is the signal `keyword_coverage_dropped` drift kind
    is built on: a substantive answer that stops citing the load-bearing
    keywords is a quality regression even when the outcome bucket is unchanged."""
    record = _r(attempts=[
        {"answer": "MAE landed around 30.", "is_acceptable": True,
         "guardrail_feedback": ""}
    ])
    question = _q(expected_keywords=["MAE", "29.95", "R²"])
    matched, total = keyword_hits(record, question)
    assert matched == 1   # only "MAE"
    assert total == 3

"""Tests for the Failure Feed pure logic (issue #31).

`classify_failure`, `select_failures`, and `group_by_session` are pure functions
over `InteractionRecord` lists; the Sentinel UI in `sentinel.py` is the only
consumer. Tests describe behaviour, not implementation — rebalance the labels
or swap the storage backend without breaking these.
"""

from datetime import datetime, timezone

from interaction_log import InteractionRecord

from failure_feed import (
    QUESTION_PREVIEW_CHARS,
    FailureRow,
    Session,
    classify_failure,
    group_by_session,
    select_failures,
)


def _record(
    timestamp: str | None = None,
    session_id: str = "sess",
    turn_index: int = 0,
    question: str = "q?",
    event_type: str = "answered",
    branch: str = "GENERIC",
    classification_confidence: float = 1.0,
    attempts: list[dict] | None = None,
    knew_answer: bool = True,
    contact_offered: bool = False,
    contact_provided: bool = False,
    latency_ms: dict | None = None,
    tool_calls: list[dict] | None = None,
    classifier_labels: list[str] | None = None,
    retrieved_chunks: list[dict] | None = None,
) -> InteractionRecord:
    return InteractionRecord.model_validate(
        {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_index": turn_index,
            "question": question,
            "event_type": event_type,
            "branch": branch,
            "classification_confidence": classification_confidence,
            "classifier_labels": classifier_labels or [branch],
            "attempts": attempts
            or [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
            "retrieved_chunks": retrieved_chunks or [],
            "tool_calls": tool_calls or [],
            "latency_ms": latency_ms
            or {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
            "knew_answer": knew_answer,
            "contact_offered": contact_offered,
            "contact_provided": contact_provided,
        }
    )


# ----- classify_failure ------------------------------------------------------


def test_classify_failure_returns_none_for_clean_turn():
    """A turn with knew_answer=True, event_type='answered', and one accepted attempt is not a failure."""
    assert classify_failure(_record()) is None


def test_classify_failure_returns_refused_for_refused_event_type():
    """event_type='refused' is the highest-precedence failure mode — the canned-refusal headline."""
    assert classify_failure(_record(event_type="refused")) == "refused"


def test_classify_failure_returns_gap_for_event_type_gap():
    """event_type='gap' is the v4 producer's gap signal (see PRD #41 / slice 1
    audit). The failure-feed contract reads event_type directly — the historical
    `not knew_answer` proxy is gone."""
    assert classify_failure(_record(event_type="gap")) == "gap"


def test_classify_failure_returns_gap_when_event_type_gap_even_if_knew_answer_true():
    """Forcing function for the slice-2 contract switch: a v4 record carrying
    event_type='gap' on a constructive GAP-branch turn (knew_answer=True because
    GAP_PHRASE isn't in the answer) is still a gap. The pre-#43 proxy would
    have missed this; the new contract catches it."""
    assert classify_failure(_record(event_type="gap", knew_answer=True)) == "gap"


def test_classify_failure_returns_retry_exhausted_when_attempts_hit_max():
    """A record with len(attempts) >= MAX_ATTEMPTS (3) and at least one rejection is 'retry-exhausted',
    distinct from 'refused' — the system burned all retries even if the final attempt accepted."""
    three_attempts = [
        {"answer": "a1", "is_acceptable": False, "guardrail_feedback": "f1"},
        {"answer": "a2", "is_acceptable": False, "guardrail_feedback": "f2"},
        {"answer": "a3", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    assert classify_failure(_record(attempts=three_attempts)) == "retry-exhausted"


def test_classify_failure_returns_rejected_then_recovered_for_short_retry():
    """A retried-but-recovered turn (rejected attempt + accepted retry, fewer than MAX_ATTEMPTS) is
    'rejected-then-recovered' — the guardrail caught and corrected without exhausting."""
    two_attempts = [
        {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "fix"},
        {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    assert classify_failure(_record(attempts=two_attempts)) == "rejected-then-recovered"


def test_classify_failure_refused_takes_precedence_over_gap():
    """A turn that's both refused and event_type='gap' is labelled 'refused' —
    the highest-severity outcome wins so the failure-mode dropdown is mutually
    exclusive. (event_type itself can't be both, but the precedence rule still
    matters for any future signal collisions.)"""
    assert classify_failure(_record(event_type="refused")) == "refused"


def test_classify_failure_gap_takes_precedence_over_retry_signals():
    """If the producer classified this as a gap, that's the headline failure
    regardless of attempt history — otherwise gap turns with retry would
    double-count under both labels."""
    two_attempts = [
        {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "fix"},
        {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    assert classify_failure(_record(event_type="gap", attempts=two_attempts)) == "gap"


def test_classify_failure_returns_deflected_for_deflected_event_type():
    """Slice 2 adds 'deflected' as a fifth failure mode (lowest severity tier).
    Surfaces individual deflected turns so the repeat_failure flag's
    target='failure_feed' click-through lands on real records."""
    assert classify_failure(_record(event_type="deflected")) == "deflected"


def test_failure_mode_constants_include_deflected_and_rank_it_lowest():
    """Slice-2 contract: 'deflected' joins the failure modes; severity rank
    parks it below 'gap' so default sort surfaces actionable failures first.
    Forcing function for the dropdown + accordion + per-mode summary chip."""
    from failure_feed import FAILURE_MODES, FAILURE_MODE_LABELS, _SEVERITY_RANK

    assert "deflected" in FAILURE_MODES
    assert "deflected" in FAILURE_MODE_LABELS
    assert _SEVERITY_RANK["deflected"] > _SEVERITY_RANK["gap"]
    assert _SEVERITY_RANK["deflected"] > _SEVERITY_RANK["refused"]


def test_failure_mode_label_for_gap_drops_knew_answer_proxy_reference():
    """Post-#43 the 'gap' label is honest about the producer signal — no
    `(knew_answer=false)` parenthetical leaking the legacy proxy into operator-
    facing copy."""
    from failure_feed import FAILURE_MODE_LABELS

    assert "knew_answer" not in FAILURE_MODE_LABELS["gap"].lower()


def test_classify_failure_deflected_takes_precedence_over_retry_signals():
    """Mirrors the gap-precedence rule for deflected turns: the producer
    classification wins over attempt history."""
    two_attempts = [
        {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "fix"},
        {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    assert classify_failure(_record(event_type="deflected", attempts=two_attempts)) == "deflected"


# ----- select_failures -------------------------------------------------------


def test_select_failures_returns_only_failure_records_with_row_columns():
    """select_failures keeps only records that classify_failure flags, and surfaces the
    dataframe columns: timestamp, branch, failure_mode, question, attempt_count, classification_confidence."""
    records = [
        _record(question="ok q"),                                              # clean — dropped
        _record(question="gap q", event_type="gap", branch="GAP",
                classification_confidence=0.42),
    ]
    rows = select_failures(records)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, FailureRow)
    assert row.failure_mode == "gap"
    assert row.branch == "GAP"
    assert row.question.startswith("gap q")
    assert row.attempt_count == 1
    assert row.classification_confidence == 0.42


def test_select_failures_branch_filter_keeps_matching_branch():
    """branch='TECHNICAL' returns only TECHNICAL failures; branch='All' returns every failure."""
    records = [
        _record(branch="GENERIC", event_type="gap"),
        _record(branch="TECHNICAL", event_type="gap"),
        _record(branch="TECHNICAL", event_type="refused"),
    ]
    technical = select_failures(records, branch="TECHNICAL")
    assert {row.branch for row in technical} == {"TECHNICAL"}
    assert len(technical) == 2

    everything = select_failures(records, branch="All")
    assert len(everything) == 3


def test_select_failures_failure_mode_filter_keeps_matching_label():
    """failure_mode='gap' returns only gap-classified rows; 'All' returns every failure mode."""
    records = [
        _record(event_type="gap"),                                  # gap
        _record(event_type="refused"),                               # refused
        _record(attempts=[
            {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "f"},
            {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
        ]),                                                          # rejected-then-recovered
    ]
    only_gap = select_failures(records, failure_mode="gap")
    assert {row.failure_mode for row in only_gap} == {"gap"}
    assert len(only_gap) == 1

    everything = select_failures(records, failure_mode="All")
    assert len(everything) == 3


def test_select_failures_question_search_is_case_insensitive_substring():
    """question_search matches a case-insensitive substring against the *full* question
    (not just the truncated preview), so a needle deep in a long question still hits."""
    long_q = "x" * 100 + " AlejandrO " + "y" * 100
    records = [
        _record(question="random thing", event_type="gap"),
        _record(question=long_q, event_type="gap"),
        _record(question="Bayesian models", event_type="gap"),
    ]
    matches = select_failures(records, question_search="alejandro")
    assert len(matches) == 1
    assert "Alejandr" in matches[0].record.question

    # Empty string acts as no filter
    assert len(select_failures(records, question_search="")) == 3


def test_select_failures_orders_rows_most_recent_first():
    """Rows are ordered by timestamp descending — the most recent failure is row 0,
    matching the issue spec: 'ordered most-recent first'."""
    older = _record(
        timestamp="2026-04-01T00:00:00+00:00", event_type="gap", question="oldest"
    )
    newest = _record(
        timestamp="2026-05-01T00:00:00+00:00", event_type="gap", question="newest"
    )
    middle = _record(
        timestamp="2026-04-15T00:00:00+00:00", event_type="gap", question="middle"
    )
    rows = select_failures([older, newest, middle])
    assert [row.record.question for row in rows] == ["newest", "middle", "oldest"]


def test_select_failures_truncates_long_questions_in_row_preview():
    """Long questions are truncated for the dataframe column with an ellipsis,
    keeping the row scannable; the full text is preserved on row.record.question."""
    long_q = "What does Alejandro think about " + "x" * 200
    rows = select_failures([_record(question=long_q, event_type="gap")])
    assert len(rows[0].question) <= QUESTION_PREVIEW_CHARS
    assert rows[0].question.endswith("…")
    assert rows[0].record.question == long_q  # full text preserved on the source record


def test_select_failures_returns_empty_list_for_empty_input():
    """Empty input → empty output; no division-by-zero, no crash."""
    assert select_failures([]) == []


# ----- group_by_session ------------------------------------------------------


def test_group_by_session_collects_records_by_session_id_with_turns_in_order():
    """group_by_session returns one Session per unique session_id; within each session,
    records are ordered by turn_index ascending — even if the input list was shuffled."""
    sessions = group_by_session(
        [
            _record(session_id="s1", turn_index=1, question="s1-t1"),
            _record(session_id="s2", turn_index=0, question="s2-t0"),
            _record(session_id="s1", turn_index=0, question="s1-t0"),
            _record(session_id="s1", turn_index=2, question="s1-t2"),
        ]
    )
    assert {s.session_id for s in sessions} == {"s1", "s2"}
    s1 = next(s for s in sessions if s.session_id == "s1")
    assert [r.question for r in s1.records] == ["s1-t0", "s1-t1", "s1-t2"]


def test_session_aggregates_turn_count_contact_flags_and_total_latency():
    """Each Session exposes turn_count, contact_offered (any turn), contact_provided (any turn),
    and total_latency_ms (sum of latency_ms.total) — drives the per-session view header."""
    records = [
        _record(session_id="s1", turn_index=0, contact_offered=False,
                latency_ms={"classifier": 0, "retrieval": 0, "generation": 0,
                            "guardrail": 0, "total": 1000}),
        _record(session_id="s1", turn_index=1, contact_offered=True, contact_provided=False,
                latency_ms={"classifier": 0, "retrieval": 0, "generation": 0,
                            "guardrail": 0, "total": 2500}),
        _record(session_id="s1", turn_index=2, contact_offered=True, contact_provided=True,
                latency_ms={"classifier": 0, "retrieval": 0, "generation": 0,
                            "guardrail": 0, "total": 4000}),
    ]
    [session] = group_by_session(records)
    assert session.turn_count == 3
    assert session.contact_offered is True   # any turn offered → True
    assert session.contact_provided is True  # any turn provided → True
    assert session.total_latency_ms == 7500


def test_session_contact_flags_default_false_when_no_turn_set_them():
    """A session whose turns never offered/provided contact reports both flags as False."""
    records = [
        _record(session_id="s1", turn_index=0),
        _record(session_id="s1", turn_index=1),
    ]
    [session] = group_by_session(records)
    assert session.contact_offered is False
    assert session.contact_provided is False


def test_group_by_session_returns_empty_list_for_empty_input():
    """Empty input → empty output; the per-session view handles 'no failures yet'."""
    assert group_by_session([]) == []

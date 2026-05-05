from datetime import datetime, timedelta, timezone

import pytest

from dashboard_model import DashboardModel
from interaction_log import InteractionRecord


def _record(
    timestamp: str | None = None,
    event_type: str = "answered",
    attempts: list[dict] | None = None,
    total_latency: int = 1000,
    turn_index: int = 0,
) -> InteractionRecord:
    return InteractionRecord.model_validate(
        {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "session_id": "sess-x",
            "turn_index": turn_index,
            "question": "q?",
            "event_type": event_type,
            "branch": "GENERIC",
            "classification_confidence": 1.0,
            "attempts": attempts or [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
            "retrieved_chunks": [],
            "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": total_latency},
            "knew_answer": True,
        }
    )


def test_total_interactions_counts_records():
    """DashboardModel.total_interactions equals the number of records it was constructed over."""
    model = DashboardModel([_record(), _record(), _record()])
    assert model.total_interactions == 3


def test_empty_record_set_returns_zero_totals_and_none_percentiles():
    """An empty DashboardModel surfaces zero counts/rates and None percentiles — never raises on division."""
    model = DashboardModel([])
    assert model.total_interactions == 0
    assert model.gap_rate == 0.0
    assert model.deflection_rate == 0.0
    assert model.guardrail_rejection_rate == 0.0
    assert model.latency_p50 is None
    assert model.latency_p95 is None


def test_gap_rate_is_fraction_of_records_with_event_type_gap():
    """gap_rate is the share of records whose event_type == 'gap' — direct
    read of the producer-emitted signal post-#42 (PRD #41 slice 1). The
    pre-#42 ``OR not knew_answer`` proxy is removed because the producer now
    emits the real value end-to-end (event_classifier covers all four
    EventType cases; LogReader smart-normalizes pre-v4 records carrying the
    canonical gap phrase).

    The discriminating case is the third record below: ``event_type=answered``
    with ``knew_answer=False`` must NOT count as a gap. The pre-#42 proxy
    counted it; the post-#42 definition does not. ``knew_answer`` is still
    written to the record for v3-record consumer compat but no longer read
    by ``gap_rate``.
    """

    def _r(event_type: str, knew_answer: bool = True):
        return InteractionRecord.model_validate(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "s",
                "turn_index": 0,
                "question": "q?",
                "event_type": event_type,
                "branch": "GENERIC",
                "classification_confidence": 1.0,
                "attempts": [{"answer": "a", "is_acceptable": True, "guardrail_feedback": ""}],
                "retrieved_chunks": [],
                "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
                "knew_answer": knew_answer,
            }
        )

    records = [
        _r("answered", knew_answer=True),    # answered with substance — not a gap
        _r("gap", knew_answer=True),         # producer-emitted gap — counts
        _r("answered", knew_answer=False),   # discriminator: pre-#42 proxy counted this; v4 definition does not
        _r("gap", knew_answer=False),        # producer-emitted gap — counts
    ]
    model = DashboardModel(records)
    assert model.gap_rate == 0.5


def test_refusal_rate_is_fraction_of_records_with_event_type_refused():
    """refusal_rate is the share whose event_type == 'refused' — the canned-refusal headline.
    Surfaces guardrail-loop exhaustion separately from gap_rate."""
    model = DashboardModel(
        [
            _record(event_type="answered"),
            _record(event_type="answered"),
            _record(event_type="refused"),
            _record(event_type="answered"),
        ]
    )
    assert model.refusal_rate == 0.25


def test_deflection_rate_is_fraction_of_records_with_event_type_deflected():
    """deflection_rate is the share of records whose event_type == 'deflected'."""
    model = DashboardModel(
        [
            _record(event_type="answered"),
            _record(event_type="deflected"),
            _record(event_type="answered"),
            _record(event_type="answered"),
        ]
    )
    assert model.deflection_rate == 0.25


def test_retry_exhausted_rate_counts_records_with_max_attempts_or_more():
    """retry_exhausted_rate counts records whose attempts list reached MAX_ATTEMPTS (3) —
    the guardrail-loop-exhaustion signal that *would* canned-refuse but might have
    finally accepted on attempt 3."""
    one_attempt = [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}]
    three_attempts = [
        {"answer": "a1", "is_acceptable": False, "guardrail_feedback": "f1"},
        {"answer": "a2", "is_acceptable": False, "guardrail_feedback": "f2"},
        {"answer": "a3", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    model = DashboardModel(
        [
            _record(attempts=one_attempt),
            _record(attempts=three_attempts),
            _record(attempts=one_attempt),
            _record(attempts=three_attempts),
        ]
    )
    assert model.retry_exhausted_rate == 0.5


def test_guardrail_rejection_rate_counts_records_with_any_unacceptable_attempt():
    """A record is 'guardrail-rejected' if any attempt was marked is_acceptable=False (i.e. retry happened)."""
    accepted_first_try = [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}]
    rejected_then_accepted = [
        {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "fix it"},
        {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    model = DashboardModel(
        [
            _record(attempts=accepted_first_try),
            _record(attempts=rejected_then_accepted),
            _record(attempts=accepted_first_try),
            _record(attempts=rejected_then_accepted),
        ]
    )
    assert model.guardrail_rejection_rate == 0.5


def test_latency_p50_and_p95_aggregate_total_latency_across_records():
    """latency_p50 / latency_p95 are percentiles over latency_ms.total across all records."""
    latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    model = DashboardModel([_record(total_latency=ms) for ms in latencies])
    assert model.latency_p50 == 550.0  # midpoint of sorted 10-value series
    assert model.latency_p95 == 955.0  # 95th percentile via linear interpolation


def test_latency_percentiles_with_single_record_return_that_value():
    """A single record yields p50 == p95 == its latency — percentile edge case."""
    model = DashboardModel([_record(total_latency=1234)])
    assert model.latency_p50 == 1234
    assert model.latency_p95 == 1234


def test_for_prior_window_returns_records_in_the_immediately_preceding_window():
    """for_prior_window(days=N) returns records timestamped between (now - 2N) and (now - N)
    days ago — exactly the window before the one for_window(days=N) covers. Drives WoW deltas.
    Per issue #36."""
    now = datetime.now(timezone.utc)
    too_old = _record(timestamp=(now - timedelta(days=20)).isoformat(), turn_index=0)        # outside (older than 14d)
    in_prior = _record(timestamp=(now - timedelta(days=10)).isoformat(), turn_index=1)       # 7-14 days ago — IN prior
    in_prior_2 = _record(timestamp=(now - timedelta(days=12)).isoformat(), turn_index=2)     # also IN prior
    in_current = _record(timestamp=(now - timedelta(days=3)).isoformat(), turn_index=3)      # in current 7d — NOT prior
    model = DashboardModel([too_old, in_prior, in_prior_2, in_current])

    prior = model.for_prior_window(days=7)
    assert isinstance(prior, DashboardModel)
    assert {r.turn_index for r in prior.records} == {1, 2}


def test_for_prior_window_with_days_none_returns_empty_dashboard():
    """for_prior_window(days=None) — no prior for the Global window. Returns an empty model
    so consumers can ask for deltas uniformly without special-casing 'Global'."""
    now = datetime.now(timezone.utc)
    model = DashboardModel([_record(timestamp=now.isoformat())])
    prior = model.for_prior_window(days=None)
    assert isinstance(prior, DashboardModel)
    assert prior.total_interactions == 0


def test_for_window_filters_records_to_last_n_days():
    """for_window(days=N) returns a new DashboardModel containing only records within the last N days."""
    now = datetime.now(timezone.utc)
    in_window = _record(timestamp=(now - timedelta(days=1)).isoformat(), turn_index=1)
    boundary = _record(timestamp=(now - timedelta(days=6, hours=23)).isoformat(), turn_index=2)
    out_of_window = _record(timestamp=(now - timedelta(days=30)).isoformat(), turn_index=3)

    model = DashboardModel([in_window, boundary, out_of_window])
    week = model.for_window(days=7)

    assert isinstance(week, DashboardModel)
    assert week.total_interactions == 2
    assert {r.turn_index for r in week.records} == {1, 2}


def _r(branch: str = "GENERIC", **overrides) -> InteractionRecord:
    """Build a record with branch override + arbitrary kwarg overrides for the routing tests."""
    base = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "s",
        "turn_index": 0,
        "question": "q?",
        "event_type": "answered",
        "branch": branch,
        "classification_confidence": 1.0,
        "classifier_labels": [branch],
        "attempts": [{"answer": "a", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
        "knew_answer": True,
    }
    base.update(overrides)
    return InteractionRecord.model_validate(base)


def test_branch_counts_returns_counter_of_records_per_branch():
    """branch_counts maps each branch label to its record count — the routing-orientation signal."""
    model = DashboardModel(
        [_r(branch="GENERIC"), _r(branch="GAP"), _r(branch="GENERIC"), _r(branch="TECHNICAL")]
    )
    assert model.branch_counts == {"GENERIC": 2, "GAP": 1, "TECHNICAL": 1}


def test_branch_distribution_returns_fractions_summing_to_one():
    """branch_distribution is the per-branch fraction. Empty model returns empty dict."""
    model = DashboardModel(
        [_r(branch="GENERIC"), _r(branch="GAP"), _r(branch="GENERIC"), _r(branch="GENERIC")]
    )
    assert model.branch_distribution == {"GENERIC": 0.75, "GAP": 0.25}
    assert DashboardModel([]).branch_distribution == {}


def test_low_confidence_rate_counts_records_below_default_threshold():
    """low_confidence_rate counts records where classification_confidence < 0.7 (default).
    Threshold is a parameter; default mirrors LIMITATIONS::O6 trip-wire."""
    model = DashboardModel(
        [
            _r(classification_confidence=0.95),
            _r(classification_confidence=0.65),
            _r(classification_confidence=0.50),
            _r(classification_confidence=0.85),
        ]
    )
    assert model.low_confidence_rate() == 0.5  # 2 of 4 below 0.7
    assert model.low_confidence_rate(threshold=0.6) == 0.25  # 1 of 4 below 0.6


def test_answered_with_substance_rate_completes_the_outcome_partition():
    """answered_with_substance_rate is the share of records the producer
    classified as substantive answers. Combined with gap_rate +
    deflection_rate + refusal_rate it forms a 4-bucket partition that sums
    to 1.0 across the record set."""
    accepted = [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}]
    records = [
        _r(event_type="answered", attempts=accepted),
        _r(event_type="answered", attempts=accepted),
        _r(event_type="gap", attempts=accepted),
        _r(event_type="deflected", attempts=accepted),
        _r(event_type="refused", attempts=accepted),
    ]
    model = DashboardModel(records)
    assert model.answered_with_substance_rate == 2 / 5
    # Partition closes
    total = (
        model.answered_with_substance_rate
        + model.gap_rate
        + model.deflection_rate
        + model.refusal_rate
    )
    assert abs(total - 1.0) < 1e-9


def test_mean_confidence_by_branch_returns_per_branch_mean():
    """mean_confidence_by_branch is the actionable Routing breakdown — the
    global `mean_classification_confidence` answers 'how sure is the
    classifier on average'; the per-branch dict answers 'on which branch is
    the classifier wobbling'. Returns one entry per observed branch; absent
    branches are absent from the dict (not 0)."""
    records = [
        _r(branch="GENERIC", classification_confidence=0.9),
        _r(branch="GENERIC", classification_confidence=0.7),
        _r(branch="TECHNICAL", classification_confidence=0.85),
        _r(branch="GAP", classification_confidence=0.5),
    ]
    model = DashboardModel(records)
    by_branch = model.mean_confidence_by_branch
    assert by_branch["GENERIC"] == pytest.approx(0.8)
    assert by_branch["TECHNICAL"] == pytest.approx(0.85)
    assert by_branch["GAP"] == pytest.approx(0.5)
    assert "BEHAVIOURAL" not in by_branch  # absent branches don't appear


def test_unique_sessions_counts_distinct_session_ids():
    """unique_sessions = number of distinct session_ids — volume orientation."""
    model = DashboardModel(
        [
            _r(session_id="s1", turn_index=0),
            _r(session_id="s1", turn_index=1),
            _r(session_id="s2", turn_index=0),
            _r(session_id="s3", turn_index=0),
            _r(session_id="s3", turn_index=1),
            _r(session_id="s3", turn_index=2),
        ]
    )
    assert model.unique_sessions == 3
    assert DashboardModel([]).unique_sessions == 0


def test_turns_per_session_median_returns_median_of_turns_per_session():
    """turns_per_session_median = statistics.median over Counter(session_id).values().
    Live data: 1.3 turns/session — engagement-collapse headline."""
    model = DashboardModel(
        [
            _r(session_id="s1", turn_index=0),                                     # s1: 1 turn
            _r(session_id="s2", turn_index=0), _r(session_id="s2", turn_index=1),  # s2: 2 turns
            _r(session_id="s3", turn_index=0), _r(session_id="s3", turn_index=1),
            _r(session_id="s3", turn_index=2),                                     # s3: 3 turns
        ]
    )
    assert model.turns_per_session_median == 2  # median([1, 2, 3]) = 2
    assert DashboardModel([]).turns_per_session_median is None


def test_dropoff_by_turn_returns_count_of_records_at_each_turn_index():
    """dropoff_by_turn = dict[turn_index -> count]. Drives the engagement-drop-off display:
    if 64 sessions have a turn 0 but only 4 have a turn 5, drop-off is steep."""
    model = DashboardModel(
        [
            _r(session_id="s1", turn_index=0),
            _r(session_id="s2", turn_index=0),
            _r(session_id="s2", turn_index=1),
            _r(session_id="s3", turn_index=0),
            _r(session_id="s3", turn_index=1),
            _r(session_id="s3", turn_index=2),
        ]
    )
    assert model.dropoff_by_turn == {0: 3, 1: 2, 2: 1}


def test_contact_offer_rate_is_share_of_records_with_contact_offered_true():
    """contact_offer_rate = count(contact_offered) / total. Live: 11/85 = 12.9%."""
    model = DashboardModel(
        [
            _r(contact_offered=True),
            _r(contact_offered=False),
            _r(contact_offered=True),
            _r(contact_offered=False),
        ]
    )
    assert model.contact_offer_rate == 0.5


def test_contact_conversion_rate_is_session_level_provided_over_offered():
    """contact_conversion_rate = sessions_provided ÷ sessions_offered.

    Session-level (not record-level) because the live pipeline writes
    `contact_provided=True` on the InteractionRecord *after* the form
    submit, so the same record never carries both flags. Record-level
    intersection always returned 0% even when the form *was* converted —
    that bug is what the session-level join fixes (see contact_log
    docstring + DECISIONS.md)."""
    # Four distinct sessions offered; one of them also has a record with
    # contact_provided=True → 1/4 = 25%.
    model = DashboardModel(
        [
            _r(session_id="s1", contact_offered=True, contact_provided=False),
            _r(session_id="s1", contact_offered=False, contact_provided=True),
            _r(session_id="s2", contact_offered=True, contact_provided=False),
            _r(session_id="s3", contact_offered=True, contact_provided=False),
            _r(session_id="s4", contact_offered=True, contact_provided=False),
        ]
    )
    assert model.contact_conversion_rate == 0.25

    no_offers = DashboardModel([_r(contact_offered=False), _r(contact_offered=False)])
    assert no_offers.contact_conversion_rate is None


def test_contact_conversion_rate_uses_provided_session_ids_cross_reference():
    """When `provided_session_ids` is supplied (Sentinel reads it from
    contacts.jsonl), conversion counts a session as converted if it appears
    in EITHER the in-log signal OR the cross-reference. Loadbearing for the
    live data — most submissions only show up in contacts.jsonl."""
    # Three sessions offered; two appear in the cross-reference; in-log
    # provided is empty (the realistic live shape).
    model = DashboardModel(
        [
            _r(session_id="s1", contact_offered=True),
            _r(session_id="s2", contact_offered=True),
            _r(session_id="s3", contact_offered=True),
        ],
        provided_session_ids=frozenset({"s1", "s2"}),
    )
    assert model.contact_conversion_rate == 2 / 3


def test_for_window_propagates_provided_session_ids_to_filtered_model():
    """`for_window` rebuilds the model — must thread the cross-ref through
    or the windowed views silently revert to the broken record-level signal."""
    full = DashboardModel(
        [
            _r(session_id="s1", contact_offered=True),
            _r(session_id="s2", contact_offered=True),
        ],
        provided_session_ids=frozenset({"s1"}),
    )
    windowed = full.for_window(days=30)
    assert windowed.provided_session_ids == frozenset({"s1"})
    assert windowed.contact_conversion_rate == 0.5


def test_technical_tool_call_rate_is_tool_call_share_of_technical_turns():
    """technical_tool_call_rate = count(branch=TECHNICAL & tool_calls!=[]) / count(branch=TECHNICAL).
    Descriptive — rate at which TECHNICAL turns invoke a tool; None when no TECHNICAL turns.
    Renamed from ``technical_tool_uptake_rate`` in PRD #41 slice 3 — "uptake" implied a target
    the system isn't trying to hit; "call rate" is purely descriptive (parallel to
    ``tool_call_count`` and ``tool_call_success_rate``)."""
    model = DashboardModel(
        [
            _r(branch="TECHNICAL", tool_calls=[{"name": "fetch_project_readme", "args": {}, "status": "success", "attempt_index": 0}]),
            _r(branch="TECHNICAL", tool_calls=[{"name": "fetch_project_readme", "args": {}, "status": "success", "attempt_index": 0}]),
            _r(branch="TECHNICAL", tool_calls=[]),
            _r(branch="GENERIC", tool_calls=[]),  # excluded — not a TECHNICAL turn
        ]
    )
    assert model.technical_tool_call_rate == 2 / 3

    no_technical = DashboardModel([_r(branch="GENERIC"), _r(branch="GAP")])
    assert no_technical.technical_tool_call_rate is None


def test_tool_call_success_rate_is_share_of_tool_calls_marked_success():
    """tool_call_success_rate = count(status=='success') / count(any status). None when
    no tool calls at all. Live: 8/8 = 100%."""
    model = DashboardModel(
        [
            _r(tool_calls=[
                {"name": "t", "args": {}, "status": "success", "attempt_index": 0},
                {"name": "t", "args": {}, "status": "error", "attempt_index": 0},
            ]),
            _r(tool_calls=[
                {"name": "t", "args": {}, "status": "success", "attempt_index": 1},
            ]),
        ]
    )
    assert model.tool_call_success_rate == 2 / 3

    no_calls = DashboardModel([_r(tool_calls=[]), _r(tool_calls=[])])
    assert no_calls.tool_call_success_rate is None


def test_latency_percentiles_returns_p50_p95_per_stage():
    """latency_percentiles(stage) generalises latency_p50/p95 across all stages —
    classifier, retrieval, generation, guardrail, total. Per issue #35: 'only total shown
    today; can't tell whether generation or guardrail is the bottleneck.'"""

    def _r_with_latency(classifier_ms: int, generation_ms: int, total_ms: int):
        return InteractionRecord.model_validate(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "s",
                "turn_index": 0,
                "question": "q?",
                "event_type": "answered",
                "branch": "GENERIC",
                "classification_confidence": 1.0,
                "attempts": [{"answer": "a", "is_acceptable": True, "guardrail_feedback": ""}],
                "retrieved_chunks": [],
                "latency_ms": {
                    "classifier": classifier_ms,
                    "retrieval": 50,
                    "generation": generation_ms,
                    "guardrail": 100,
                    "total": total_ms,
                },
                "knew_answer": True,
            }
        )

    records = [
        _r_with_latency(classifier_ms=100, generation_ms=1000, total_ms=2000),
        _r_with_latency(classifier_ms=200, generation_ms=2000, total_ms=4000),
        _r_with_latency(classifier_ms=300, generation_ms=3000, total_ms=6000),
        _r_with_latency(classifier_ms=400, generation_ms=4000, total_ms=8000),
        _r_with_latency(classifier_ms=500, generation_ms=5000, total_ms=10000),
    ]
    model = DashboardModel(records)

    gen = model.latency_percentiles("generation")
    assert gen[50] == 3000.0
    assert gen[95] == pytest.approx(4800.0, rel=0.05)

    cls = model.latency_percentiles("classifier")
    assert cls[50] == 300.0

    # Existing latency_p50 / latency_p95 properties still work (delegate to total)
    assert model.latency_p50 == 6000.0


def test_latency_percentiles_returns_none_per_percentile_when_no_records():
    """Empty model → None for each requested percentile (no data, no answer)."""
    model = DashboardModel([])
    out = model.latency_percentiles("total")
    assert out == {50: None, 95: None}


def test_latency_percentiles_accepts_custom_percentile_list():
    """Percentile list is overridable — gives flexibility for ad-hoc deeper inspection."""

    def _r_with_total(total_ms: int):
        return InteractionRecord.model_validate(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "s",
                "turn_index": 0,
                "question": "q?",
                "event_type": "answered",
                "branch": "GENERIC",
                "classification_confidence": 1.0,
                "attempts": [{"answer": "a", "is_acceptable": True, "guardrail_feedback": ""}],
                "retrieved_chunks": [],
                "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": total_ms},
                "knew_answer": True,
            }
        )

    model = DashboardModel([_r_with_total(ms) for ms in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)])
    out = model.latency_percentiles("total", percentiles=(25, 75, 99))
    assert set(out.keys()) == {25, 75, 99}
    assert out[25] == 325.0
    assert out[75] == 775.0


def test_for_window_with_days_none_returns_self_unchanged():
    """for_window(days=None) is the 'Global' window — returns the same records, no filtering.
    Per issue #35: WINDOWS = [(Global, None), (30d, 30), (7d, 7)]."""
    now = datetime.now(timezone.utc)
    records = [
        _record(timestamp=(now - timedelta(days=1)).isoformat(), turn_index=1),
        _record(timestamp=(now - timedelta(days=100)).isoformat(), turn_index=2),
    ]
    model = DashboardModel(records)
    out = model.for_window(days=None)
    assert out.total_interactions == 2
    assert {r.turn_index for r in out.records} == {1, 2}


def test_time_series_by_day_empty_records_returns_empty_list():
    """time_series_by_day([]) returns [] — no fabricated dates from no data. Empty model
    is a valid state; the chart layer renders an 'insufficient data' placeholder."""
    model = DashboardModel([])
    assert model.time_series_by_day("gap_rate", days=7) == []


def test_time_series_by_day_single_day_returns_full_window_with_one_populated_day():
    """For days=N, the result has exactly N entries (one per UTC day in the window),
    and the day containing the records carries the metric value; other days are None."""
    from datetime import date as _date
    today = datetime.now(timezone.utc).date()
    record = _record(timestamp=datetime.now(timezone.utc).isoformat(), event_type="answered")
    model = DashboardModel([record])

    series = model.time_series_by_day("gap_rate", days=3)
    assert len(series) == 3
    dates = [d for d, _ in series]
    assert dates == sorted(dates)  # ascending
    assert today in dates
    today_value = next(v for d, v in series if d == today)
    assert today_value == 0.0  # one clean record → 0% gap
    # Earlier days have no records → None
    other_values = [v for d, v in series if d != today]
    assert all(v is None for v in other_values), "days without records must be None, not 0"
    # Every entry's first element is a date object
    assert all(isinstance(d, _date) for d, _ in series)


def test_time_series_by_day_aggregates_per_day_records_with_gaps_as_none():
    """Multiple records on the same day collapse into one metric value computed over that
    day's records; days with no records render as None — never zero, so the chart can
    distinguish 'no data' from 'a real 0% rate'."""
    from datetime import time

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    # Anchor record timestamps to mid-day UTC on the target date so the test
    # is midnight-safe (offsets-from-now used to roll into the previous date
    # when the suite ran around 00:00 UTC).
    def _on_date(d, hour):
        return datetime.combine(d, time(hour=hour), tzinfo=timezone.utc).isoformat()

    # Today: 1 gap of 4 → 25% gap_rate
    today_records = [
        _record(timestamp=_on_date(today, 9)),                       # clean
        _record(timestamp=_on_date(today, 11), event_type="gap"),
        _record(timestamp=_on_date(today, 13)),                      # clean
        _record(timestamp=_on_date(today, 15)),                      # clean
    ]
    # Two-days-ago: 2 records, 1 gap → 50%
    two_days_ago_records = [
        _record(timestamp=_on_date(two_days_ago, 10)),
        _record(timestamp=_on_date(two_days_ago, 14), event_type="gap"),
    ]
    model = DashboardModel(today_records + two_days_ago_records)

    series = dict(model.time_series_by_day("gap_rate", days=3))
    assert series[today] == 0.25
    assert series[yesterday] is None  # no records → None, not 0.0
    assert series[two_days_ago] == 0.5


def test_time_series_by_day_with_days_none_spans_earliest_record_to_today():
    """days=None is the All-time window: series starts at the earliest record's date and
    ends today (UTC), filling intervening days with None when no records hit them."""
    now = datetime.now(timezone.utc)
    today = now.date()
    five_days_ago = (now - timedelta(days=5))
    records = [
        _record(timestamp=five_days_ago.isoformat()),
        _record(timestamp=now.isoformat()),
    ]
    series = model = DashboardModel(records).time_series_by_day("gap_rate", days=None)

    assert len(series) == 6  # five_days_ago, -4d, -3d, -2d, -1d, today
    assert series[0][0] == five_days_ago.date()
    assert series[-1][0] == today
    # Bookend days have records → 0.0; middle days → None
    assert series[0][1] == 0.0
    assert series[-1][1] == 0.0
    middle_values = [v for _, v in series[1:-1]]
    assert all(v is None for v in middle_values)


def test_metric_getters_covers_every_thresholded_metric():
    """Every thresholded metric must have a getter so the Trend Explorer can
    plot it. The reverse isn't required — a metric can have a getter (for
    trending / orientation display) without a threshold (e.g. tool uptake,
    where the denominator caveat makes the threshold misleading)."""
    from dashboard_model import METRIC_GETTERS
    from metric_status import THRESHOLDS

    missing = set(THRESHOLDS) - set(METRIC_GETTERS)
    assert not missing, (
        f"Thresholded metrics without a getter: {missing}. "
        "Add lambdas to METRIC_GETTERS so the Trend Explorer can plot them."
    )


def test_time_series_by_day_works_for_every_plottable_metric():
    """Calling time_series_by_day(metric, days=1) for each registered metric must not raise
    and must return a list whose single value is either a number or None — exercises every
    getter against a real (synthetic) record so plumbing failures surface in tests, not at runtime."""
    from dashboard_model import METRIC_GETTERS

    record = InteractionRecord.model_validate(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": "sess-x",
            "turn_index": 0,
            "question": "q?",
            "event_type": "answered",
            "branch": "TECHNICAL",
            "classification_confidence": 0.9,
            "classifier_labels": ["TECHNICAL"],
            "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
            "retrieved_chunks": [],
            "tool_calls": [{"name": "fetch_project_readme", "args": {}, "status": "success", "attempt_index": 0}],
            "latency_ms": {"classifier": 100, "retrieval": 200, "generation": 300, "guardrail": 400, "total": 1000},
            "knew_answer": True,
            "contact_offered": True,
            "contact_provided": True,
        }
    )
    model = DashboardModel([record])
    for metric in METRIC_GETTERS:
        series = model.time_series_by_day(metric, days=1)
        assert len(series) == 1
        value = series[0][1]
        assert value is None or isinstance(value, (int, float)), (
            f"{metric}: got {value!r}"
        )


def _canary_record(branch: str = "TECHNICAL", **overrides) -> InteractionRecord:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "canary-sess",
        "turn_index": 0,
        "question": "C001",
        "event_type": "answered",
        "branch": branch,
        "classification_confidence": 0.95,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
        "knew_answer": True,
        "is_canary": True,
        "run_id": "run-1",
        "replicate_index": 0,
    }
    payload.update(overrides)
    return InteractionRecord.model_validate(payload)


def test_dashboard_model_excludes_canary_records_by_default():
    """Live tabs construct DashboardModel(records) and never see canary records:
    aggregations operate on the live subset only. Default include_canary=False
    is the canonical filter for Metrics / Trends / Failures."""
    live = _record(event_type="answered")
    canary = _canary_record(event_type="gap", branch="GAP").model_copy(
        update={"knew_answer": False}
    )
    model = DashboardModel([live, canary])

    assert model.total_interactions == 1
    assert model.gap_rate == 0.0


def test_dashboard_model_only_canary_inverts_the_filter():
    """The Canary tab constructs DashboardModel(records, include_canary=True,
    only_canary=True) — aggregations operate on the canary subset only."""
    live = _record(event_type="answered")
    canary = _canary_record(event_type="gap").model_copy(update={"knew_answer": False})
    model = DashboardModel([live, canary], include_canary=True, only_canary=True)

    assert model.total_interactions == 1
    assert model.gap_rate == 1.0


def test_dashboard_model_include_canary_keeps_both_subsets():
    """include_canary=True without only_canary mixes live + canary — escape hatch
    for ad-hoc analysis. The default-off behaviour is the load-bearing one."""
    live = _record(event_type="answered")
    canary = _canary_record()
    model = DashboardModel([live, canary], include_canary=True)
    assert model.total_interactions == 2


def test_outcome_accuracy_is_fraction_of_records_with_outcome_matching_expected():
    """outcome_accuracy(corpus) is the headline canary correctness signal post-#45:
    fraction of canary records whose derived outcome equals the corpus's
    expected_outcome. Replaces the pre-#45 branch_match_rate (mechanism →
    outcome contract)."""
    from canary_corpus import CanaryQuestion

    corpus = [
        CanaryQuestion(id="C001", question="q1",
                       expected_outcome="answered_with_substance",
                       expected_keywords=[], must_not_appear=[],
                       expected_chunk_sources=[], category="x"),
        CanaryQuestion(id="C002", question="q2",
                       expected_outcome="gap_acknowledged",
                       expected_keywords=[], must_not_appear=[],
                       expected_chunk_sources=[], category="x"),
    ]
    records = [
        _canary_record(question="q1", event_type="answered"),
        _canary_record(question="q2", event_type="answered"),  # answered when should have gap'd
    ]
    model = DashboardModel(records, include_canary=True, only_canary=True)
    assert model.outcome_accuracy(corpus) == 0.5


def test_keyword_coverage_is_share_of_expected_keywords_present_on_substantive_answers():
    """keyword_coverage(corpus) aggregates per-record keyword hits across canary
    records whose corpus question is answered_with_substance + has expected_keywords.
    Other outcomes are skipped (gap-acknowledgement coverage is a tautology — the
    gap phrase contract gates correctness via derive_outcome instead)."""
    from canary_corpus import CanaryQuestion

    corpus = [
        CanaryQuestion(id="C001", question="q1",
                       expected_outcome="answered_with_substance",
                       expected_keywords=["MAE", "29.95"], must_not_appear=[],
                       expected_chunk_sources=[], category="x"),
        CanaryQuestion(id="C002", question="q2",
                       expected_outcome="gap_acknowledged",
                       expected_keywords=["I don't have"], must_not_appear=[],
                       expected_chunk_sources=[], category="x"),
    ]
    records = [
        _canary_record(question="q1", event_type="answered").model_copy(
            update={"attempts": [{"answer": "Final MAE 29.95.",
                                  "is_acceptable": True, "guardrail_feedback": ""}]},
        ),
        _canary_record(question="q2", event_type="gap").model_copy(
            update={"attempts": [{"answer": "I don't have hands-on with that.",
                                  "is_acceptable": True, "guardrail_feedback": ""}]},
        ),
    ]
    model = DashboardModel(records, include_canary=True, only_canary=True)
    # only q1 contributes (q2 is gap_acknowledged); q1 has 2/2 keywords → 1.0
    assert model.keyword_coverage(corpus) == 1.0


def test_red_flag_rate_is_fraction_of_records_with_must_not_appear_substring_hit():
    """red_flag_rate(corpus) is the fabrication-detection signal post-#45:
    fraction of canary records whose answer text contains any per-question
    must_not_appear substring."""
    from canary_corpus import CanaryQuestion

    corpus = [
        CanaryQuestion(id="C001", question="q1",
                       expected_outcome="gap_acknowledged",
                       expected_keywords=[],
                       must_not_appear=["I have used kdb"],
                       expected_chunk_sources=[], category="x"),
        CanaryQuestion(id="C002", question="q2",
                       expected_outcome="answered_with_substance",
                       expected_keywords=[], must_not_appear=[],
                       expected_chunk_sources=[], category="x"),
    ]
    records = [
        _canary_record(question="q1", event_type="gap").model_copy(
            update={"attempts": [{"answer": "Yes, I have used kdb at scale.",
                                  "is_acceptable": True, "guardrail_feedback": ""}]},
        ),
        _canary_record(question="q2", event_type="answered"),
    ]
    model = DashboardModel(records, include_canary=True, only_canary=True)
    assert model.red_flag_rate(corpus) == 0.5


def test_event_counts_buckets_records_by_event_type():
    """event_counts returns the count of each event_type seen across the records."""
    model = DashboardModel(
        [
            _record(event_type="answered"),
            _record(event_type="answered"),
            _record(event_type="gap"),
            _record(event_type="deflected"),
            _record(event_type="refused"),
            _record(event_type="answered"),
        ]
    )
    assert model.event_counts == {"answered": 3, "gap": 1, "deflected": 1, "refused": 1}

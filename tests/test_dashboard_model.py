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


def test_gap_rate_unions_knew_answer_false_with_event_type_gap():
    """gap_rate counts a record if EITHER event_type=='gap' OR knew_answer=False — issue #35
    redefinition. Live-log inventory showed event_type=='gap' is essentially never written
    (writer bug), but knew_answer=False fires 9.4% of the time. Sentinel must use the union
    until the pipeline writer is fixed."""

    def _r(event_type: str, knew_answer: bool):
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
        _r("answered", True),    # neither — not a gap
        _r("gap", True),         # event_type=='gap' alone — gap
        _r("answered", False),   # knew_answer=False alone — gap (the live-data case)
        _r("gap", False),        # both — gap (counted once, not twice)
    ]
    model = DashboardModel(records)
    assert model.gap_rate == 0.75


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


def test_confident_failure_rate_counts_high_confidence_failures():
    """confident_failure_rate counts records where confidence >= 0.8 AND a failure signal fires
    (knew_answer=False OR any rejected attempt OR event_type='refused'). This catches the
    misroutes that low_confidence_rate cannot — the system was certain and still failed.
    Per issue #35 'Detection gap'."""
    rejected_then_accepted = [
        {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "fix"},
        {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
    ]
    accepted = [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}]

    records = [
        _r(classification_confidence=0.95, knew_answer=True, attempts=accepted),                     # confident success — not counted
        _r(classification_confidence=0.95, knew_answer=False, attempts=accepted),                     # confident gap — counted
        _r(classification_confidence=0.95, knew_answer=True, attempts=rejected_then_accepted),       # confident retry — counted
        _r(classification_confidence=0.95, knew_answer=True, event_type="refused", attempts=accepted),  # confident refusal — counted
        _r(classification_confidence=0.50, knew_answer=False, attempts=accepted),                     # low-conf gap — NOT counted (different metric)
    ]
    model = DashboardModel(records)
    assert model.confident_failure_rate() == 0.6  # 3 of 5
    # Threshold parameter overridable
    assert model.confident_failure_rate(threshold=0.99) == 0.0


def test_multi_label_rate_excludes_records_with_empty_classifier_labels_from_denominator():
    """multi_label_rate = count(len(labels)>1) / count(labels populated). Records with empty
    classifier_labels (the legacy v1 ones) are excluded from the denominator — otherwise
    a fully-blank corpus would report 0% as if multi-label routing were never working,
    when really the data just isn't there. Returns None when denominator is 0."""
    model = DashboardModel(
        [
            _r(classifier_labels=["GENERIC"]),
            _r(classifier_labels=["GAP", "TECHNICAL"]),
            _r(classifier_labels=["TECHNICAL"]),
            _r(classifier_labels=["GAP", "GENERIC", "TECHNICAL"]),
            _r(classifier_labels=[]),  # excluded from denominator
        ]
    )
    assert model.multi_label_rate == 0.5  # 2 of 4 populated have len>1

    # All-empty population — None, not 0.0
    only_empty = DashboardModel([_r(classifier_labels=[]), _r(classifier_labels=[])])
    assert only_empty.multi_label_rate is None


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


def test_contact_conversion_rate_is_provided_over_offered_or_none():
    """contact_conversion_rate = count(contact_provided) / count(contact_offered). None when
    nothing offered (live: 1/11 = ~9% — contact-form-failure headline)."""
    model = DashboardModel(
        [
            _r(contact_offered=True, contact_provided=True),
            _r(contact_offered=True, contact_provided=False),
            _r(contact_offered=True, contact_provided=False),
            _r(contact_offered=True, contact_provided=False),
            _r(contact_offered=False, contact_provided=False),
        ]
    )
    assert model.contact_conversion_rate == 0.25  # 1 of 4 offered

    no_offers = DashboardModel([_r(contact_offered=False), _r(contact_offered=False)])
    assert no_offers.contact_conversion_rate is None


def test_technical_tool_uptake_rate_is_tool_use_share_of_technical_turns():
    """technical_tool_uptake_rate = count(branch=TECHNICAL & tool_calls!=[]) / count(branch=TECHNICAL).
    Live: 6/9 = 66.7% — LIMITATIONS::P8 first measurement. None when no TECHNICAL turns."""
    model = DashboardModel(
        [
            _r(branch="TECHNICAL", tool_calls=[{"name": "fetch_project_readme", "args": {}, "status": "success", "attempt_index": 0}]),
            _r(branch="TECHNICAL", tool_calls=[{"name": "fetch_project_readme", "args": {}, "status": "success", "attempt_index": 0}]),
            _r(branch="TECHNICAL", tool_calls=[]),
            _r(branch="GENERIC", tool_calls=[]),  # excluded — not a TECHNICAL turn
        ]
    )
    assert model.technical_tool_uptake_rate == 2 / 3

    no_technical = DashboardModel([_r(branch="GENERIC"), _r(branch="GAP")])
    assert no_technical.technical_tool_uptake_rate is None


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

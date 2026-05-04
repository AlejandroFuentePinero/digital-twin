from datetime import datetime, timedelta, timezone

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
    """gap_rate is the share of records whose event_type == 'gap'."""
    model = DashboardModel(
        [
            _record(event_type="answered"),
            _record(event_type="gap"),
            _record(event_type="answered"),
            _record(event_type="gap"),
        ]
    )
    assert model.gap_rate == 0.5


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

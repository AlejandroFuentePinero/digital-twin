"""Tests for the FlagDetector module (issue #34).

Three pure detector functions over `InteractionRecord` lists + cached cluster
files. No I/O inside the detector. Tests build records relative to "now" so
window filters operate on real timestamps (matches the cluster_gaps.py and
dashboard_model.py test convention).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from interaction_log import InteractionRecord


def _record(
    timestamp: str | None = None,
    session_id: str = "sess",
    turn_index: int = 0,
    question: str = "q?",
    event_type: str = "answered",
    branch: str = "GAP",
    knew_answer: bool = True,
    attempts: list[dict] | None = None,
) -> InteractionRecord:
    return InteractionRecord.model_validate(
        {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_index": turn_index,
            "question": question,
            "event_type": event_type,
            "branch": branch,
            "classification_confidence": 0.9,
            "attempts": attempts
            or [{"answer": "ans", "is_acceptable": True, "guardrail_feedback": ""}],
            "retrieved_chunks": [],
            "tool_calls": [],
            "latency_ms": {
                "classifier": 0, "retrieval": 0, "generation": 0,
                "guardrail": 0, "total": 0,
            },
            "knew_answer": knew_answer,
        }
    )


# ----- detect_gap_rate_jump --------------------------------------------------


def test_detect_gap_rate_jump_fires_when_current_week_exceeds_prior_by_threshold():
    """Tracer bullet: a >30pp WoW gap-rate jump emits one Flag pointing at the
    Trend Explorer. Threshold is the absolute pp delta (matches the existing
    `wow_delta` convention — fractions == pp throughout the codebase).

    Post-#42: ``DashboardModel.gap_rate`` reads the real producer-emitted
    ``event_type=='gap'`` signal, so test records carry ``event_type`` directly
    instead of toggling the legacy ``knew_answer`` proxy."""
    from flag_detector import detect_gap_rate_jump

    now = datetime.now(timezone.utc)
    # Prior week: 1 gap out of 10 records → 10% gap rate
    prior_week = [
        _record(
            timestamp=(now - timedelta(days=10)).isoformat(),
            session_id=f"prior-{i}",
            event_type="gap" if i == 0 else "answered",
        )
        for i in range(10)
    ]
    # Current week: 5 gaps out of 10 records → 50% gap rate. Jump = 40pp.
    current_week = [
        _record(
            timestamp=(now - timedelta(days=2)).isoformat(),
            session_id=f"current-{i}",
            event_type="gap" if i < 5 else "answered",
        )
        for i in range(10)
    ]

    flags = detect_gap_rate_jump(prior_week + current_week)

    assert len(flags) == 1
    flag = flags[0]
    assert flag.kind == "gap_rate_jump"
    assert flag.target == "trend"


def test_detect_gap_rate_jump_does_not_fire_on_stable_week_over_week_rates():
    """Stable / quiet weeks must not produce false positives — that's the
    whole point of having a threshold. Same gap rate this week and last week
    → no flag."""
    from flag_detector import detect_gap_rate_jump

    now = datetime.now(timezone.utc)
    # Both windows: 1 gap out of 10 → 10% gap rate. WoW delta = 0.
    records = [
        _record(
            timestamp=(now - timedelta(days=10)).isoformat(),
            session_id=f"prior-{i}",
            event_type="gap" if i == 0 else "answered",
        )
        for i in range(10)
    ] + [
        _record(
            timestamp=(now - timedelta(days=2)).isoformat(),
            session_id=f"current-{i}",
            event_type="gap" if i == 0 else "answered",
        )
        for i in range(10)
    ]

    assert detect_gap_rate_jump(records) == []


def test_detect_gap_rate_jump_handles_empty_records_without_firing():
    """Empty record set → no flag. The detector must never crash on an empty
    history (matches the "no false positives on quiet data" AC)."""
    from flag_detector import detect_gap_rate_jump

    assert detect_gap_rate_jump([]) == []


def test_detect_gap_rate_jump_does_not_fire_when_no_prior_week_history_exists():
    """Single-week-only history (e.g. fresh deployment) — prior window is
    empty so its gap rate is 0. A non-zero current rate would otherwise
    register as a jump *from* a baseline that was never measured. Don't
    fire until there's a real prior-week comparison to make."""
    from flag_detector import detect_gap_rate_jump

    now = datetime.now(timezone.utc)
    # Only current-week records; high gap rate but nothing to compare against.
    records = [
        _record(
            timestamp=(now - timedelta(days=2)).isoformat(),
            session_id=f"current-{i}",
            knew_answer=(i >= 5),
        )
        for i in range(10)
    ]

    assert detect_gap_rate_jump(records) == []


# ----- detect_new_cluster ----------------------------------------------------


def _clusters_payload(*labels: str) -> dict:
    """Build a `gap_clusters.json`-shaped dict with the supplied cluster labels."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": 7,
        "clusters": [
            {"label": label, "count": 2, "examples": [f"q1 {label}", f"q2 {label}"]}
            for label in labels
        ],
    }


def test_detect_new_cluster_fires_for_labels_absent_from_every_prior_file():
    """A label present in this week's clusters but in none of the priors is the
    canonical 'new topic showed up' signal — emit one Flag per such label."""
    from flag_detector import detect_new_cluster

    current = _clusters_payload("AWS / cloud", "kdb+", "Rust")
    priors = [
        _clusters_payload("AWS / cloud", "kdb+"),
        _clusters_payload("AWS / cloud"),
    ]
    flags = detect_new_cluster(current, priors)

    assert [f.kind for f in flags] == ["new_cluster"]
    assert all(f.target == "gap_clusters" for f in flags)
    assert "Rust" in flags[0].headline


def test_detect_new_cluster_returns_no_flags_when_current_file_missing():
    """`gap_clusters.json` missing → no flags. AC: must not crash. The Cluster
    panel renders its own placeholder; no need to also raise a flag for the
    absence."""
    from flag_detector import detect_new_cluster

    assert detect_new_cluster(None, [_clusters_payload("kdb+")]) == []


def test_detect_new_cluster_does_not_fire_on_cold_start_with_no_prior_history():
    """First run ever — there's no prior cluster file. Every label would
    trivially count as 'new', producing a wave of false positives. Establish
    the baseline silently; the next week's run is the first that can flag."""
    from flag_detector import detect_new_cluster

    current = _clusters_payload("AWS / cloud", "kdb+")
    assert detect_new_cluster(current, []) == []


def test_detect_new_cluster_emits_no_flags_when_every_label_overlaps_priors():
    """Stable / quiet weeks must not produce false positives. Every current
    label appears in at least one prior file → no new clusters → no flags."""
    from flag_detector import detect_new_cluster

    current = _clusters_payload("AWS / cloud", "kdb+")
    priors = [_clusters_payload("AWS / cloud"), _clusters_payload("kdb+")]
    assert detect_new_cluster(current, priors) == []


# ----- detect_repeat_failure -------------------------------------------------


def _deflected(question: str, days_ago: float, session: str) -> InteractionRecord:
    """Build a deflected record at `days_ago` from now with the given question."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return _record(
        question=question,
        event_type="deflected",
        knew_answer=False,
        session_id=session,
        timestamp=ts,
    )


def test_detect_repeat_failure_fires_when_same_question_deflected_threshold_times():
    """Tracer bullet for repeat_failure: 3 deflected records of the same question
    within 7 days emits one Flag pointing at the Failure Feed."""
    from flag_detector import detect_repeat_failure

    records = [
        _deflected("Have you used kdb+/q?", days_ago=1, session="a"),
        _deflected("Have you used kdb+/q?", days_ago=3, session="b"),
        _deflected("Have you used kdb+/q?", days_ago=5, session="c"),
    ]
    flags = detect_repeat_failure(records)

    assert len(flags) == 1
    flag = flags[0]
    assert flag.kind == "repeat_failure"
    assert flag.target == "failure_feed"
    assert "kdb+" in flag.headline


def test_detect_repeat_failure_does_not_fire_below_threshold():
    """2 occurrences of the same deflected question shouldn't fire — threshold
    is ≥3. Anything less is noise."""
    from flag_detector import detect_repeat_failure

    records = [
        _deflected("Q?", days_ago=1, session="a"),
        _deflected("Q?", days_ago=2, session="b"),
    ]
    assert detect_repeat_failure(records) == []


def test_detect_repeat_failure_ignores_occurrences_outside_seven_day_window():
    """Two recent + one stale (8 days ago) → only 2 in-window. Below threshold,
    no flag. The window is what makes 'repeat' a recent-pattern signal vs an
    all-time tally."""
    from flag_detector import detect_repeat_failure

    records = [
        _deflected("Q?", days_ago=1, session="a"),
        _deflected("Q?", days_ago=2, session="b"),
        _deflected("Q?", days_ago=8, session="c"),  # outside window
    ]
    assert detect_repeat_failure(records) == []


def test_detect_repeat_failure_counts_refused_and_deflected_together():
    """The spec says 'deflected/refused' — both event types count toward the
    repeat threshold. Mixed mode (1 deflected + 2 refused on the same question)
    still trips the flag."""
    from flag_detector import detect_repeat_failure

    now = datetime.now(timezone.utc)
    records = [
        _deflected("Q?", days_ago=1, session="a"),
        _record(
            question="Q?",
            event_type="refused",
            knew_answer=False,
            session_id="b",
            timestamp=(now - timedelta(days=2)).isoformat(),
        ),
        _record(
            question="Q?",
            event_type="refused",
            knew_answer=False,
            session_id="c",
            timestamp=(now - timedelta(days=3)).isoformat(),
        ),
    ]
    flags = detect_repeat_failure(records)
    assert len(flags) == 1
    assert flags[0].kind == "repeat_failure"


def test_detect_repeat_failure_is_case_insensitive_for_question_match():
    """Visitors phrase the same question with different capitalisation. The
    match should be case-insensitive + whitespace-trimmed so 'kdb+/q?' and
    '  KDB+/Q?  ' count as the same question."""
    from flag_detector import detect_repeat_failure

    records = [
        _deflected("Have you used kdb+/q?", days_ago=1, session="a"),
        _deflected("HAVE YOU USED KDB+/Q?", days_ago=2, session="b"),
        _deflected("  have you used kdb+/q?  ", days_ago=3, session="c"),
    ]
    flags = detect_repeat_failure(records)
    assert len(flags) == 1


def test_detect_repeat_failure_handles_empty_records_without_firing():
    """Empty record set → no flag. AC: empty record set must not crash."""
    from flag_detector import detect_repeat_failure

    assert detect_repeat_failure([]) == []

"""Tests for the gap-clustering batch (issue #32).

The batch is a weekly LLM call; tests mock at the `litellm.completion` boundary
per `docs/TESTING.md` (no LLM API calls in tests). The pure helpers
(`extract_gap_questions`, `write_clusters`, `read_clusters`) are tested
directly. The CLI is tested end-to-end with tmp paths + a mocked LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

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


# ----- extract_gap_questions -------------------------------------------------


def test_extract_gap_questions_keeps_records_with_knew_answer_false():
    """The canonical gap signal in live data is knew_answer=False (per the
    dashboard_model.gap_rate live-data note). extract_gap_questions surfaces
    those questions for clustering."""
    from cluster_gaps import extract_gap_questions

    records = [
        _record(question="Have you written CUDA kernels?", knew_answer=False),
        _record(question="Have you used kdb+/q?", knew_answer=False),
    ]
    questions = extract_gap_questions(records, days=None)
    assert questions == [
        "Have you written CUDA kernels?",
        "Have you used kdb+/q?",
    ]


def test_extract_gap_questions_drops_clean_and_refused_records():
    """Clean answers (knew_answer=True) and refused turns are not gap signals
    even if they look like they could be — failure_feed.classify_failure
    treats refused with higher precedence than gap, so clustering should not
    surface refused-question text."""
    from cluster_gaps import extract_gap_questions

    records = [
        _record(question="clean q", knew_answer=True),
        _record(question="refused q", knew_answer=False, event_type="refused"),
        _record(question="gap q", knew_answer=False),
    ]
    assert extract_gap_questions(records, days=None) == ["gap q"]


def test_extract_gap_questions_window_filter_drops_records_outside_n_days():
    """The CLI's --days flag drives a trailing window: a 30-day-old gap turn
    must not appear when --days=7. Older clusters dilute 'this week's pattern'
    in the cached file."""
    from cluster_gaps import extract_gap_questions

    now = datetime.now(timezone.utc)
    fresh = _record(
        question="recent gap",
        knew_answer=False,
        timestamp=(now - timedelta(days=2)).isoformat(),
    )
    stale = _record(
        question="old gap",
        knew_answer=False,
        timestamp=(now - timedelta(days=30)).isoformat(),
    )
    assert extract_gap_questions([fresh, stale], days=7) == ["recent gap"]


# ----- GapClusterer ----------------------------------------------------------


def _completion_returning(json_text: str):
    """Build a SimpleNamespace mimicking litellm.completion's structured-output response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json_text))]
    )


def test_gap_clusterer_returns_empty_list_without_calling_llm_for_empty_input():
    """No questions → no LLM call. Spending tokens on an empty batch is wasteful
    and breaks structured-output parsing (the model has nothing to label)."""
    from cluster_gaps import GapClusterer

    with patch("cluster_gaps.completion") as mock:
        clusters = GapClusterer().cluster([])
    assert clusters == []
    assert mock.call_count == 0


def test_gap_clusterer_parses_llm_batch_into_cluster_dataclasses():
    """The clusterer makes one batched LLM call and parses the structured JSON
    into list[Cluster] with label/count/examples fields. Tests the I/O boundary;
    the actual clustering quality is the model's concern, not unit tests'."""
    from cluster_gaps import Cluster, GapClusterer

    response_json = json.dumps({
        "clusters": [
            {
                "label": "AWS / cloud",
                "count": 3,
                "examples": [
                    "Have you used AWS?",
                    "Do you have AWS Lambda experience?",
                    "Have you deployed to AWS?",
                ],
            },
            {
                "label": "kdb+ / time-series databases",
                "count": 2,
                "examples": ["Have you used kdb+?", "Have you written q?"],
            },
        ]
    })
    questions = [
        "Have you used AWS?",
        "Do you have AWS Lambda experience?",
        "Have you deployed to AWS?",
        "Have you used kdb+?",
        "Have you written q?",
    ]
    with patch("cluster_gaps.completion", return_value=_completion_returning(response_json)):
        clusters = GapClusterer().cluster(questions)

    assert clusters == [
        Cluster(label="AWS / cloud", count=3, examples=[
            "Have you used AWS?",
            "Do you have AWS Lambda experience?",
            "Have you deployed to AWS?",
        ]),
        Cluster(label="kdb+ / time-series databases", count=2, examples=[
            "Have you used kdb+?",
            "Have you written q?",
        ]),
    ]


def test_gap_clusterer_drops_clusters_smaller_than_min_size():
    """Clusters with count < CLUSTER_MIN_SIZE (=2) are filtered out — singletons
    don't help an operator spot a recurring pattern, they just clutter the panel."""
    from cluster_gaps import CLUSTER_MIN_SIZE, GapClusterer

    assert CLUSTER_MIN_SIZE == 2
    response_json = json.dumps({
        "clusters": [
            {"label": "real cluster", "count": 3,
             "examples": ["q1", "q2", "q3"]},
            {"label": "singleton — should drop", "count": 1, "examples": ["solo"]},
        ]
    })
    with patch("cluster_gaps.completion", return_value=_completion_returning(response_json)):
        clusters = GapClusterer().cluster(["q1", "q2", "q3", "solo"])

    assert [c.label for c in clusters] == ["real cluster"]


# ----- write_clusters / read_clusters ----------------------------------------


def test_write_and_read_clusters_round_trip_with_required_top_level_fields(tmp_path):
    """The on-disk JSON shape is {generated_at, period_days, clusters: [...]}
    per the issue spec. Sentinel reads only this shape — drift breaks the panel
    silently, so the round-trip is the contract test."""
    from cluster_gaps import Cluster, read_clusters, write_clusters

    out_path = tmp_path / "gap_clusters.json"
    clusters = [
        Cluster(label="AWS / cloud", count=3,
                examples=["Have you used AWS?", "AWS Lambda?", "AWS deploys?"]),
        Cluster(label="kdb+", count=2, examples=["kdb+?", "q?"]),
    ]
    write_clusters(clusters, period_days=7, out_path=out_path)

    # On-disk shape — explicit because Sentinel reads the raw JSON, not Cluster objects
    raw = json.loads(out_path.read_text())
    assert set(raw.keys()) == {"generated_at", "period_days", "clusters"}
    assert raw["period_days"] == 7
    assert raw["clusters"] == [
        {"label": "AWS / cloud", "count": 3,
         "examples": ["Have you used AWS?", "AWS Lambda?", "AWS deploys?"]},
        {"label": "kdb+", "count": 2, "examples": ["kdb+?", "q?"]},
    ]
    # generated_at is an ISO-8601 timestamp — parseable
    datetime.fromisoformat(raw["generated_at"])

    # read_clusters returns the same dict-shape so the panel can render it directly
    assert read_clusters(out_path) == raw


def test_read_clusters_returns_none_when_file_absent(tmp_path):
    """Missing file → None. Sentinel's panel reads None and renders the
    'run cluster_gaps.py' placeholder instead of crashing."""
    from cluster_gaps import read_clusters

    assert read_clusters(tmp_path / "nope.json") is None


# ----- CLI end-to-end --------------------------------------------------------


def test_run_batch_reads_log_file_and_writes_clustered_output_json(tmp_path):
    """End-to-end: feed a tmp interactions.jsonl with mixed gap/non-gap records,
    mock the LLM, run the batch, and assert gap_clusters.json is the expected
    shape with the LLM's clusters serialised. Mocks the LLM at the boundary —
    the real path everywhere else: read jsonl → extract → cluster → write json."""
    from cluster_gaps import run_batch

    log_path = tmp_path / "interactions.jsonl"
    out_path = tmp_path / "gap_clusters.json"

    now = datetime.now(timezone.utc)
    records = [
        # 3 gap turns within the window
        _record(question="Have you used AWS?", knew_answer=False,
                timestamp=(now - timedelta(days=1)).isoformat()),
        _record(question="AWS Lambda?", knew_answer=False,
                timestamp=(now - timedelta(days=2)).isoformat()),
        _record(question="Have you used kdb+?", knew_answer=False,
                timestamp=(now - timedelta(days=3)).isoformat()),
        # Non-gap turn — should be ignored
        _record(question="clean q", knew_answer=True),
        # Old gap turn — outside the 7-day window
        _record(question="ancient gap", knew_answer=False,
                timestamp=(now - timedelta(days=30)).isoformat()),
    ]
    log_path.write_text("\n".join(r.model_dump_json() for r in records) + "\n")

    response_json = json.dumps({
        "clusters": [
            {"label": "AWS / cloud", "count": 2,
             "examples": ["Have you used AWS?", "AWS Lambda?"]},
            {"label": "kdb+", "count": 1, "examples": ["Have you used kdb+?"]},
        ]
    })
    with patch("cluster_gaps.completion", return_value=_completion_returning(response_json)) as mock:
        run_batch(days=7, out_path=out_path, log_path=log_path)

    # The LLM was called exactly once with all in-window gap questions
    assert mock.call_count == 1
    user_msg = mock.call_args.kwargs["messages"][-1]["content"]
    assert "Have you used AWS?" in user_msg
    assert "AWS Lambda?" in user_msg
    assert "Have you used kdb+?" in user_msg
    assert "ancient gap" not in user_msg     # window filter applied before LLM
    assert "clean q" not in user_msg         # non-gap filtered out

    # Output file matches the documented shape; singletons dropped
    payload = json.loads(out_path.read_text())
    assert payload["period_days"] == 7
    assert payload["clusters"] == [
        {"label": "AWS / cloud", "count": 2,
         "examples": ["Have you used AWS?", "AWS Lambda?"]},
    ]

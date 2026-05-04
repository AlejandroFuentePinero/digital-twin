"""Tests for the failure-summarisation batch (issue #33).

Same shape as test_cluster_gaps.py: pure helpers tested directly, the LLM is
mocked at the `litellm.completion` boundary, and the CLI is exercised
end-to-end with tmp paths + a mocked LLM. No LLM API calls in tests
(`docs/TESTING.md`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from interaction_log import InteractionRecord


def _record(
    timestamp: str | None = None,
    session_id: str = "sess",
    turn_index: int = 0,
    question: str = "q?",
    event_type: str = "answered",
    branch: str = "GENERIC",
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


def _completion_returning(text: str):
    """SimpleNamespace mimicking litellm.completion's response shape."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


# ----- select_records_for_group ----------------------------------------------


def test_select_records_for_group_gap_uses_classify_failure_precedence():
    """The 'gap' group is what failure_feed.classify_failure flags as 'gap' —
    knew_answer=False without refused-precedence kicking in. Reusing the
    canonical predicate avoids drift with Failure Feed and the cluster batch."""
    from summarize_failures import select_records_for_group

    records = [
        _record(question="clean", knew_answer=True),
        _record(question="gap q", knew_answer=False),
        _record(question="refused q", event_type="refused", knew_answer=False),  # refused, NOT gap
    ]
    selected = select_records_for_group(records, group="gap", days=None)
    assert [r.question for r in selected] == ["gap q"]


def test_select_records_for_group_unacceptable_includes_any_rejected_attempt():
    """The 'unacceptable' group is every record with at least one
    is_acceptable=False attempt — covers both rejected-then-recovered AND
    retry-exhausted. The summary tells the operator 'where did the writer
    misfire', so the recovery vs exhaustion distinction matters less here than
    in Failure Feed."""
    from summarize_failures import select_records_for_group

    rejected_then_recovered = _record(
        question="recovered",
        attempts=[
            {"answer": "bad", "is_acceptable": False, "guardrail_feedback": "fix"},
            {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
        ],
    )
    retry_exhausted = _record(
        question="exhausted",
        attempts=[
            {"answer": "a1", "is_acceptable": False, "guardrail_feedback": "f1"},
            {"answer": "a2", "is_acceptable": False, "guardrail_feedback": "f2"},
            {"answer": "a3", "is_acceptable": False, "guardrail_feedback": "f3"},
        ],
    )
    clean = _record(question="clean")
    records = [rejected_then_recovered, retry_exhausted, clean]

    selected = select_records_for_group(records, group="unacceptable", days=None)
    assert {r.question for r in selected} == {"recovered", "exhausted"}


def test_select_records_for_group_deflection_uses_deflected_event_type():
    """The 'deflection' group is the canonical event_type=='deflected' check
    (CONTEXT.md: 'Deflection' — system-prompt rule that triggers on behavioural
    questions, logged with event_type='deflected'). Distinct from gap and refused."""
    from summarize_failures import select_records_for_group

    records = [
        _record(question="answered", event_type="answered"),
        _record(question="deflected", event_type="deflected"),
        _record(question="refused", event_type="refused"),
        _record(question="gap", knew_answer=False),
    ]
    selected = select_records_for_group(records, group="deflection", days=None)
    assert [r.question for r in selected] == ["deflected"]


def test_select_records_for_group_window_filter_drops_records_outside_n_days():
    """The CLI's --days flag drives a trailing window: an old record (outside
    the window) must not appear even when its predicate matches."""
    from summarize_failures import select_records_for_group

    now = datetime.now(timezone.utc)
    fresh = _record(
        question="recent gap", knew_answer=False,
        timestamp=(now - timedelta(days=2)).isoformat(),
    )
    stale = _record(
        question="old gap", knew_answer=False,
        timestamp=(now - timedelta(days=30)).isoformat(),
    )
    selected = select_records_for_group([fresh, stale], group="gap", days=7)
    assert [r.question for r in selected] == ["recent gap"]


# ----- FailureSummarizer -----------------------------------------------------


def test_failure_summarizer_returns_placeholder_without_calling_llm_for_empty_records():
    """Empty records → no LLM call. A summary of zero records is just 'no
    records this period' — burning tokens to discover that is wasteful and
    structured-output parsing has nothing to anchor against."""
    from summarize_failures import FailureSummarizer

    with patch("summarize_failures.completion") as mock:
        text = FailureSummarizer().summarize([], group="gap", period_days=7)

    assert mock.call_count == 0
    # Some marker so a downstream reader can tell 'this batch ran, found nothing'
    # apart from 'this batch never ran'
    assert text.strip(), "empty-group summary must still produce *some* text"
    assert "gap" in text.lower() or "no" in text.lower()


def test_failure_summarizer_calls_gpt_4_1_with_record_questions_and_returns_markdown():
    """One LLM call to gpt-4.1 (per PRD: 'writing quality matters'); the user
    prompt carries the group's questions; the LLM's response text is the
    summary returned verbatim. Records → prompt → response is the I/O contract;
    actual writing quality is the model's concern."""
    from summarize_failures import SUMMARIZER_MODEL, FailureSummarizer

    records = [
        _record(question="Have you used AWS?", knew_answer=False),
        _record(question="Do you know Spark?", knew_answer=False),
    ]
    expected_md = "## Cloud + distributed compute gaps\n\nTwo questions probe..."
    with patch(
        "summarize_failures.completion",
        return_value=_completion_returning(expected_md),
    ) as mock:
        text = FailureSummarizer().summarize(records, group="gap", period_days=7)

    assert text == expected_md
    # Boundary: model is gpt-4.1 (writing quality)
    assert mock.call_args.kwargs["model"] == SUMMARIZER_MODEL
    # User prompt mentions the questions verbatim — they're the summary's input
    user_msg = next(
        m["content"] for m in mock.call_args.kwargs["messages"] if m["role"] == "user"
    )
    assert "Have you used AWS?" in user_msg
    assert "Do you know Spark?" in user_msg
    # Group framing reaches the model so it knows what kind of summary to write
    assert "gap" in user_msg.lower()


# ----- write_summary / latest_summary_path / read_summary --------------------


def test_write_summary_creates_group_dated_md_file_with_text_contents(tmp_path):
    """Filename is `{group}_{YYYY-MM-DD}.md` so multiple runs across days don't
    clobber each other and `latest_summary_path` can sort by date suffix."""
    from summarize_failures import write_summary

    text = "## Recurring AWS questions\n\nTwo questions...\n"
    path = write_summary(text, group="gap", date="2026-05-04", out_dir=tmp_path)

    assert path.name == "gap_2026-05-04.md"
    assert path.parent == tmp_path
    assert path.read_text() == text


def test_latest_summary_path_picks_most_recent_date_suffix(tmp_path):
    """When multiple `{group}_*.md` files exist, latest_summary_path returns the
    one with the highest YYYY-MM-DD suffix; date strings sort lexicographically
    so `sorted()` is enough — no datetime parsing required."""
    from summarize_failures import latest_summary_path, write_summary

    write_summary("old", group="deflection", date="2026-04-01", out_dir=tmp_path)
    write_summary("new", group="deflection", date="2026-05-04", out_dir=tmp_path)
    # Sibling group must not interfere
    write_summary("other", group="gap", date="2026-05-10", out_dir=tmp_path)

    latest = latest_summary_path("deflection", tmp_path)
    assert latest is not None
    assert latest.name == "deflection_2026-05-04.md"


def test_latest_summary_path_returns_none_when_no_files_exist(tmp_path):
    """Missing dir / no matching files → None; the panel reads None and renders
    the 'run summarize_failures.py' placeholder instead of crashing."""
    from summarize_failures import latest_summary_path

    assert latest_summary_path("deflection", tmp_path / "nonexistent") is None
    assert latest_summary_path("deflection", tmp_path) is None  # empty dir


def test_read_summary_returns_latest_text_or_none(tmp_path):
    """read_summary is the panel's one-liner: latest text or None. The Sentinel
    formatter switches on the None case to render the 'run summarize_failures.py'
    placeholder."""
    from summarize_failures import read_summary, write_summary

    assert read_summary("deflection", tmp_path) is None  # nothing written yet

    write_summary("old text", group="deflection", date="2026-04-01", out_dir=tmp_path)
    write_summary("latest text", group="deflection", date="2026-05-04", out_dir=tmp_path)
    assert read_summary("deflection", tmp_path) == "latest text"


# ----- run_batch CLI end-to-end ----------------------------------------------


def test_run_batch_writes_one_file_per_group_with_dated_names(tmp_path):
    """End-to-end: a tmp interactions.jsonl with at least one record per group
    + a mocked LLM → run_batch writes unacceptable_/deflection_/gap_*.md in the
    target dir. All three files are produced even if a group is empty (then the
    file carries the no-records placeholder)."""
    from summarize_failures import run_batch

    log_path = tmp_path / "interactions.jsonl"
    out_dir = tmp_path / "summaries"

    records = [
        # gap turn
        _record(question="Have you used Spark?", knew_answer=False),
        # deflected turn
        _record(question="Tell me about a conflict", event_type="deflected"),
        # unacceptable turn (rejected then recovered)
        _record(question="how does X work?", attempts=[
            {"answer": "guess", "is_acceptable": False, "guardrail_feedback": "fix"},
            {"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""},
        ]),
        # clean turn — should not appear in any group
        _record(question="clean q"),
    ]
    log_path.write_text("\n".join(r.model_dump_json() for r in records) + "\n")

    fake_response = _completion_returning("# Summary\n\nMocked summary text.")
    with patch("summarize_failures.completion", return_value=fake_response) as mock:
        paths = run_batch(days=7, out_dir=out_dir, log_path=log_path)

    # All three files present, named per the date-stamped convention
    written = sorted(p.name for p in paths)
    today = datetime.now(timezone.utc).date().isoformat()
    assert written == sorted([
        f"deflection_{today}.md",
        f"gap_{today}.md",
        f"unacceptable_{today}.md",
    ])
    for path in paths:
        assert path.exists()

    # LLM called exactly three times — one per non-empty group
    assert mock.call_count == 3


def test_run_batch_short_circuits_groups_with_no_records_to_placeholder(tmp_path):
    """An entirely empty log → run_batch still writes 3 placeholder files but
    makes 0 LLM calls. Always-present files keep the dashboard's
    'is the batch ever run?' check trivial."""
    from summarize_failures import run_batch

    log_path = tmp_path / "interactions.jsonl"
    log_path.write_text("")  # empty log
    out_dir = tmp_path / "summaries"

    with patch("summarize_failures.completion") as mock:
        paths = run_batch(days=7, out_dir=out_dir, log_path=log_path)

    assert mock.call_count == 0
    assert len(paths) == 3
    today = datetime.now(timezone.utc).date().isoformat()
    for group in ("unacceptable", "deflection", "gap"):
        path = out_dir / f"{group}_{today}.md"
        assert path.exists(), f"missing {path}"
        assert "no" in path.read_text().lower()


def test_run_batch_excludes_canary_records_from_every_group(tmp_path):
    """Forcing function (#39): canary records share interactions.jsonl with
    live records. summarize_failures must filter `is_canary=True` before
    selecting any of the three groups (gap / unacceptable / deflection) —
    canary refusal / gap / deflection probes (C006-C009, C019-C022, C047-C050)
    would otherwise pollute the operator-facing summary reports.

    With only canary records in the log, every group falls back to the
    no-records placeholder and the LLM is never called."""
    from summarize_failures import run_batch

    log_path = tmp_path / "interactions.jsonl"
    out_dir = tmp_path / "summaries"

    canary_records = [
        _record(question="canary gap", knew_answer=False).model_copy(
            update={"is_canary": True, "run_id": "run-A", "replicate_index": 0}
        ),
        _record(question="canary deflection", event_type="deflected").model_copy(
            update={"is_canary": True, "run_id": "run-A", "replicate_index": 1}
        ),
        _record(question="canary unacceptable", attempts=[
            {"answer": "x", "is_acceptable": False, "guardrail_feedback": "fix"},
            {"answer": "y", "is_acceptable": True, "guardrail_feedback": ""},
        ]).model_copy(
            update={"is_canary": True, "run_id": "run-A", "replicate_index": 2}
        ),
    ]
    log_path.write_text(
        "\n".join(r.model_dump_json() for r in canary_records) + "\n"
    )

    with patch("summarize_failures.completion") as mock:
        run_batch(days=7, out_dir=out_dir, log_path=log_path)

    assert mock.call_count == 0, (
        "canary records leaked into summary batch — operator-facing summaries "
        "would mix synthetic canary probes with live failures"
    )

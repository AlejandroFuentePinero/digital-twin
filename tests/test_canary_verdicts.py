"""Tests for the canary verdict store and report (issue #53)."""

from __future__ import annotations

from pathlib import Path

from canary_verdicts import (
    ReplicateVerdict,
    format_report,
    read_run_verdicts,
    write_run_verdicts,
)


def _row(qid: str, rep: int, passed: bool, reason: str = "fine") -> ReplicateVerdict:
    return ReplicateVerdict(
        question_id=qid, question=f"question {qid}", replicate_index=rep,
        passed=passed, reason=reason, answer=f"answer {qid} {rep}",
    )


def test_a_run_that_was_never_judged_reads_as_none(tmp_path: Path):
    """No verdict file means the run was not judged, distinct from an empty pass."""
    assert read_run_verdicts("run-x", tmp_path) is None


def test_a_question_passes_only_when_every_replicate_passes(tmp_path: Path):
    """Strict roll-up: one failing replicate fails the question; replicates come back in order."""
    write_run_verdicts("run-x", [
        _row("C002", 2, True), _row("C001", 0, True), _row("C002", 0, True),
        _row("C002", 1, False, "Claims CUDA work."), _row("C001", 1, True),
    ], tmp_path)

    by_id = {v.question_id: v for v in read_run_verdicts("run-x", tmp_path)}

    assert by_id["C001"].passed is True
    assert by_id["C002"].passed is False
    assert [r.replicate_index for r in by_id["C002"].replicates] == [0, 1, 2]


def test_report_leads_with_the_pass_count_and_lists_each_failure_with_its_reason(
    tmp_path: Path,
):
    """The printed report opens with the pass count, then one line per failing replicate."""
    write_run_verdicts("run-x", [
        _row("C001", 0, True), _row("C002", 0, False, "Says it has no information."),
    ], tmp_path)

    first_line, *rest = format_report(read_run_verdicts("run-x", tmp_path)).splitlines()

    assert first_line == "1 of 2 questions pass"
    assert rest == [
        "FAIL C002 replicate 0: question C002 | Says it has no information."
    ]

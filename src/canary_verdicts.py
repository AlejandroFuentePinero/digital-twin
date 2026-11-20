"""Canary verdict store (issue #53): one JSONL file per run under
``data/canaries/verdicts/<run_id>.jsonl``, one line per judged replicate.

The canary is a regression test. A question passes only when every one of
its replicates passes: each replicate is an answer a visitor could get.

Verdicts live beside the corpus, not in the interaction log, because they are
written after the run by a separate judge pass and can be re-written for an
older run (`canary_runner.judge_run`) without touching logged records.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_VERDICTS_DIR = Path(__file__).parent.parent / "data" / "canaries" / "verdicts"


@dataclass(frozen=True)
class ReplicateVerdict:
    question_id: str
    question: str
    replicate_index: int
    passed: bool
    reason: str
    answer: str


@dataclass(frozen=True)
class QuestionVerdict:
    question_id: str
    question: str
    passed: bool
    replicates: list[ReplicateVerdict]


def write_run_verdicts(
    run_id: str, rows: list[ReplicateVerdict], verdicts_dir: Path = DEFAULT_VERDICTS_DIR,
) -> Path:
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    path = verdicts_dir / f"{run_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    return path


def read_run_verdicts(
    run_id: str, verdicts_dir: Path = DEFAULT_VERDICTS_DIR,
) -> list[QuestionVerdict] | None:
    """Per-question verdicts for one run, in corpus id order; None when the
    run was never judged."""
    path = verdicts_dir / f"{run_id}.jsonl"
    if not path.exists():
        return None
    by_question: dict[str, list[ReplicateVerdict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = ReplicateVerdict(**json.loads(line))
            by_question.setdefault(row.question_id, []).append(row)
    return [
        QuestionVerdict(
            question_id=qid,
            question=reps[0].question,
            passed=all(r.passed for r in reps),
            replicates=sorted(reps, key=lambda r: r.replicate_index),
        )
        for qid, reps in sorted(by_question.items())
    ]


def format_report(verdicts: list[QuestionVerdict]) -> str:
    """Pass count first, then one line per failing replicate with its reason."""
    passing = sum(v.passed for v in verdicts)
    lines = [f"{passing} of {len(verdicts)} questions pass"]
    for v in verdicts:
        for r in v.replicates:
            if not r.passed:
                lines.append(
                    f"FAIL {v.question_id} replicate {r.replicate_index}: "
                    f"{v.question} | {r.reason}"
                )
    return "\n".join(lines)

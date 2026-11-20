"""Canary runner — replays the corpus through the current Pipeline (issue #39).

CLI entry point that loads ``data/canaries/corpus.json``, runs N=3 replicates
per question through a fresh Pipeline, and writes ``is_canary=True`` records
to the canonical ``data/logs/interactions.jsonl``. Optional
``--freeze-baseline`` promotes the just-completed run to the frozen golden
baseline pointer.

Tests inject a `pipeline_factory` so the suite never hits a real LLM
(``docs/TESTING.md``: no LLM API calls in tests). The factory returns a
pipeline-like object with a ``run(question, history, session_id, turn_index,
**_)`` method; the runner threads a `_CanaryLogWriter` into the factory so
every record the pipeline appends carries the canary metadata
(``is_canary=True``, shared ``run_id``, current ``replicate_index``).

Cousins: `cluster_gaps.run_batch` and `summarize_failures.run_batch` are the
closest cousins for CLI shape. Their ``--days`` flag is replaced here by
``--replicates``; both share ``--out-dir``-style log path overrides for
testability.
"""

from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from canary_baseline import DEFAULT_BASELINE_PATH, freeze_baseline
from canary_corpus import DEFAULT_CORPUS_PATH, load_canaries
from canary_judge import Verdict, judge, shown_answer
from canary_verdicts import (
    DEFAULT_VERDICTS_DIR,
    ReplicateVerdict,
    format_report,
    read_run_verdicts,
    write_run_verdicts,
)
from interaction_log import DEFAULT_LOG_PATH, InteractionRecord, LogWriter
from log_reader import LocalReader

DEFAULT_REPLICATES = 3
JUDGE_WORKERS = 8  # judge calls in flight; each is one gpt-6.2-sol request


def _new_run_id() -> str:
    """``run-YYYYMMDD-hhmmss-<rand6>`` — sortable + unique. The random suffix
    prevents collisions when multiple runs land in the same second
    (`secrets.token_hex(3)` = 6 hex chars)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{secrets.token_hex(3)}"


class _CanaryLogWriter:
    """Wraps an inner LogWriter to inject canary metadata into every record.

    The runner instantiates this once per batch, threads it into the
    pipeline factory, and updates ``replicate_index`` between calls. This
    keeps the Pipeline code path canary-unaware: the only difference between
    a live turn and a canary turn is the wrapper around the writer."""

    def __init__(self, inner: LogWriter, *, run_id: str):
        self._inner = inner
        self._run_id = run_id
        self.replicate_index: int = 0

    def append(self, record: dict | InteractionRecord) -> None:
        if isinstance(record, dict):
            record = {
                **record,
                "is_canary": True,
                "run_id": self._run_id,
                "replicate_index": self.replicate_index,
            }
        else:
            record = record.model_copy(update={
                "is_canary": True,
                "run_id": self._run_id,
                "replicate_index": self.replicate_index,
            })
        self._inner.append(record)


def _build_default_pipeline(writer):
    """Default factory: build a Pipeline with the same wiring as `app.py`.

    Imports are lazy so test imports of `canary_runner` don't pay the cost
    of constructing classifier/composer/generator at collection time (they
    pull `litellm`, `chromadb`, etc. and the env-var checks)."""
    from branches import REGISTRY
    from classifier import Classifier
    from composer import PromptComposer
    from generator import Generator
    from guardrail import Guardrail
    from pipeline import Pipeline
    from profile import ProfileLoader
    from tools import ToolRegistry, make_litellm_tool_callable

    profile = ProfileLoader()
    composer = PromptComposer(profile, REGISTRY)
    tool_registry = ToolRegistry(
        Path(__file__).parent.parent / "data" / "readmes" / "registry.json"
    )
    return Pipeline(
        classifier=Classifier(),
        composer=composer,
        generator=Generator(),
        guardrail=Guardrail(),
        log_writer=writer,
        tool_registry=tool_registry,
        tool_model_callable=make_litellm_tool_callable(),
    )


def run_batch(
    *,
    replicates: int = DEFAULT_REPLICATES,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    log_path: Path | None = None,
    pipeline_factory: Callable[[Any], Any] = _build_default_pipeline,
    freeze_baseline_after: bool = False,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    judge_fn: Callable[[InteractionRecord, Any], Verdict] = judge,
    verdicts_dir: Path = DEFAULT_VERDICTS_DIR,
) -> str:
    """Replay the corpus N replicates per question through one Pipeline, then
    judge every replicate (issue #53) and write the run's verdict file.

    Returns the ``run_id`` so the CLI can echo it (and so callers driving
    fix-verification flows can re-judge this run)."""
    canonical_writer = LogWriter(log_path or DEFAULT_LOG_PATH)
    run_id = _new_run_id()
    canary_writer = _CanaryLogWriter(canonical_writer, run_id=run_id)
    pipeline = pipeline_factory(canary_writer)
    questions = load_canaries(corpus_path)

    for q in questions:
        for replicate_index in range(replicates):
            canary_writer.replicate_index = replicate_index
            session_id = f"canary-{run_id}-{q.id}"
            pipeline.run(
                question=q.question,
                history=[],
                session_id=session_id,
                turn_index=replicate_index,
            )

    judge_run(
        run_id,
        corpus_path=corpus_path,
        log_path=log_path or DEFAULT_LOG_PATH,
        judge_fn=judge_fn,
        verdicts_dir=verdicts_dir,
    )

    if freeze_baseline_after:
        from pipeline import GIT_SHA
        freeze_baseline(run_id, frozen_git_sha=GIT_SHA, path=baseline_path)
    return run_id


def judge_run(
    run_id: str,
    *,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    judge_fn: Callable[[InteractionRecord, Any], Verdict] = judge,
    verdicts_dir: Path = DEFAULT_VERDICTS_DIR,
) -> Path:
    """Judge every replicate of a logged canary run and write its verdict
    file. Also back-fills runs logged before the judge existed. Records whose
    question is no longer in the corpus are skipped: there is nothing to
    grade them against."""
    corpus = {q.question: q for q in load_canaries(corpus_path)}
    records = [
        r for r in LocalReader(log_path).read()
        if r.is_canary and r.run_id == run_id and r.question in corpus
    ]
    ordered = sorted(records, key=lambda r: (corpus[r.question].id, r.replicate_index or 0))
    with ThreadPoolExecutor(JUDGE_WORKERS) as pool:
        verdicts = list(pool.map(lambda r: judge_fn(r, corpus[r.question]), ordered))
    rows = []
    for r, verdict in zip(ordered, verdicts):
        q = corpus[r.question]
        rows.append(ReplicateVerdict(
            question_id=q.id,
            question=q.question,
            replicate_index=r.replicate_index or 0,
            passed=verdict.passed,
            reason=verdict.reason,
            answer=shown_answer(r),
        ))
    return write_run_verdicts(run_id, rows, verdicts_dir)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Replay the canary corpus through the current Pipeline."
    )
    parser.add_argument(
        "--replicates", type=int, default=DEFAULT_REPLICATES,
        help=f"Replicates per question (default {DEFAULT_REPLICATES}).",
    )
    parser.add_argument(
        "--corpus", type=Path, default=DEFAULT_CORPUS_PATH,
        help=f"Corpus JSON path (default {DEFAULT_CORPUS_PATH}).",
    )
    parser.add_argument(
        "--freeze-baseline", action="store_true",
        help="Promote the just-completed run to the frozen golden baseline.",
    )
    parser.add_argument(
        "--judge-run", metavar="RUN_ID",
        help="Judge an already-logged run instead of replaying the corpus.",
    )
    args = parser.parse_args()
    if args.judge_run:
        judge_run(args.judge_run, corpus_path=args.corpus)
        print(format_report(read_run_verdicts(args.judge_run)))
        return
    run_id = run_batch(
        replicates=args.replicates,
        corpus_path=args.corpus,
        freeze_baseline_after=args.freeze_baseline,
    )
    print(f"Canary run complete: run_id={run_id}")
    print(format_report(read_run_verdicts(run_id)))
    if args.freeze_baseline:
        print(f"Baseline frozen to {DEFAULT_BASELINE_PATH}")


if __name__ == "__main__":
    main()

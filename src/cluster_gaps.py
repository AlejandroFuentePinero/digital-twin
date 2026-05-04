"""Gap-clustering batch (issue #32).

Sentinel's Cluster panel reads a cached `gap_clusters.json` written by this
module's CLI. The batch runs weekly (operator cadence — no scheduler), reads
the canonical interaction log over a trailing window, calls the LLM once with
every gap question, and writes the labelled clusters to disk.

Sentinel never calls the LLM at page-load — that would tie dashboard latency to
LLM availability and burn tokens on every refresh. The batch + cached-file
split keeps the dashboard fast and offline-safe.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from litellm import completion
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from failure_feed import classify_failure
from interaction_log import InteractionRecord


BATCH_DEFAULT_DAYS = 7
CLUSTER_MIN_SIZE = 2

# Sentinel reads from this path at page-load when no override is supplied.
DEFAULT_OUT_PATH = (
    Path(__file__).parent.parent / "data" / "logs" / "gap_clusters.json"
)

# Cheap classifier-tier model — this is a one-shot batch over a small (≤ ~50)
# question list with structured output, not a high-stakes generation. Mirrors
# classifier.py's choice for the same reasoning.
MODEL = "openai/gpt-4.1-nano"


SYSTEM_PROMPT = """\
You are clustering gap questions from a portfolio chatbot's interaction log. \
Each question is one a visitor asked that the chatbot answered with the gap \
phrase ("I don't have that information in my knowledge base"). Group the \
questions by the underlying skill, technology, or topic the visitor was \
probing.

Return a JSON object with one field:
- `clusters`: a list of objects, each with
  - `label`: a short noun phrase naming the cluster (e.g. "AWS / cloud", "kdb+ / time-series databases")
  - `count`: the number of questions in this cluster (integer)
  - `examples`: a list of up to 3 representative question strings drawn verbatim from the input

A question may belong to exactly one cluster. Singletons are allowed but will \
be filtered downstream — produce them anyway so the count is accurate.\
"""


@dataclass(frozen=True)
class Cluster:
    """One cluster of similar gap questions. The label/count/examples shape is
    the public contract — Sentinel's panel and the on-disk JSON read these fields."""
    label: str
    count: int
    examples: list[str]


class _ClusterModel(BaseModel):
    label: str
    count: int
    examples: list[str]


class _ClustererResponse(BaseModel):
    clusters: list[_ClusterModel]


_wait = wait_exponential(multiplier=1, min=10, max=120)
_stop = stop_after_attempt(5)


class GapClusterer:
    MODEL = MODEL

    @retry(wait=_wait, stop=_stop)
    def cluster(self, questions: list[str]) -> list[Cluster]:
        """Group ``questions`` into labelled clusters via one batched LLM call."""
        if not questions:
            return []
        user_prompt = "Questions to cluster:\n" + "\n".join(
            f"- {q}" for q in questions
        )
        response = completion(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=_ClustererResponse,
        )
        parsed = _ClustererResponse.model_validate_json(
            response.choices[0].message.content
        )
        return [
            Cluster(label=c.label, count=c.count, examples=list(c.examples))
            for c in parsed.clusters
            if c.count >= CLUSTER_MIN_SIZE
        ]


def write_clusters(
    clusters: list[Cluster], period_days: int, out_path: Path
) -> None:
    """Serialise to ``{generated_at, period_days, clusters: [...]}`` JSON.

    The on-disk shape is the contract Sentinel reads — keep stable.
    """
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": period_days,
        "clusters": [asdict(c) for c in clusters],
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))


def read_clusters(path: Path) -> dict | None:
    """Load the cached cluster file; return ``None`` when absent so the panel
    can render the 'run cluster_gaps.py' placeholder instead of crashing."""
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def run_batch(
    *,
    days: int,
    out_path: Path,
    log_path: Path | None = None,
) -> Path:
    """Read the interaction log, extract recent gap questions, cluster them via
    the LLM, and write `gap_clusters.json`. Returns the output path so the CLI
    can print it.

    `log_path=None` defaults to the canonical interactions.jsonl via LocalReader.
    """
    from log_reader import LocalReader

    reader = LocalReader(log_path) if log_path is not None else LocalReader()
    records = reader.read()
    questions = extract_gap_questions(records, days=days)
    clusters = GapClusterer().cluster(questions)
    write_clusters(clusters, period_days=days, out_path=out_path)
    return Path(out_path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Cluster recent gap questions via one LLM batch call."
    )
    parser.add_argument(
        "--days", type=int, default=BATCH_DEFAULT_DAYS,
        help=f"Trailing window in days (default {BATCH_DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_PATH,
        help=f"Output JSON path (default {DEFAULT_OUT_PATH}).",
    )
    args = parser.parse_args()
    written = run_batch(days=args.days, out_path=args.out)
    print(f"Wrote {written}")


if __name__ == "__main__":
    main()


def extract_gap_questions(
    records: list[InteractionRecord], days: int | None
) -> list[str]:
    """Pull the question strings from gap turns in the last ``days`` window.

    Reuses the canonical gap signal (``classify_failure(r) == 'gap'``); see
    `failure_feed.classify_failure` for the precedence rules — refused turns
    take precedence over gap, so refused-question text never enters clustering.
    """
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        records = [r for r in records if r.timestamp >= cutoff]
    return [r.question for r in records if classify_failure(r) == "gap"]

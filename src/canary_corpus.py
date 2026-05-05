"""Canary corpus — pure data inventory (issue #39, recalibrated in PRD #41 / #45).

50 curated questions designed against the live KB so every "answered" entry is
grounded in real content. Loaded once into a list of `CanaryQuestion` objects;
`canary_runner.py` replays them N=3 times per question through the current
pipeline, and `canary_drift.py` cross-references the corpus to compute drift
flags (outcome accuracy, keyword coverage, red-flag emergence, retry depth,
chunk-set Jaccard, latency).

Validation is a forcing function: `load_canaries()` re-resolves every
`expected_outcome` against the four-bucket `Outcome` literal at load time. A
typo or removed bucket fails on import rather than silently producing
meaningless drift signals at run time. Pre-#45 the field was `expected_branch`
validated against `branches.REGISTRY` — the new contract measures outcome
quality rather than which branch fired.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from canary_outcome import Outcome  # noqa: E402  (resolved at runtime)

DEFAULT_CORPUS_PATH = (
    Path(__file__).parent.parent / "data" / "canaries" / "corpus.json"
)

_OUTCOMES = frozenset(get_args(Outcome))


@dataclass(frozen=True)
class CanaryQuestion:
    """One curated canary entry. The full set lives in
    ``data/canaries/corpus.json``; the runner replays it N replicates per
    question through ``Pipeline.run`` and the drift detector reads the
    `expected_*` / `must_not_appear` fields to compute drift kinds without
    LLM-as-judge.

    `expected_keywords` is load-bearing for `keyword_coverage` on
    ``answered_with_substance`` outcomes. `must_not_appear` is the
    fabrication-detection contract — populated for gap / refused /
    out-of-scope outcomes where a specific shape would constitute a
    fabrication. `expected_chunk_sources` stays descriptive for future
    retrieval-drift extensions."""
    id: str
    question: str
    expected_outcome: Outcome
    expected_keywords: list[str]
    must_not_appear: list[str]
    expected_chunk_sources: list[str]
    category: str


def load_canaries(path: Path = DEFAULT_CORPUS_PATH) -> list[CanaryQuestion]:
    """Parse corpus.json into a list of `CanaryQuestion`. Validates each
    entry's `expected_outcome` against the `Outcome` literal — typo / removed
    bucket fails at load time, before any replay starts."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    questions: list[CanaryQuestion] = []
    for entry in raw:
        outcome = entry["expected_outcome"]
        if outcome not in _OUTCOMES:
            raise ValueError(
                f"Canary {entry.get('id', '?')}: expected_outcome={outcome!r} "
                f"is not a valid Outcome ({sorted(_OUTCOMES)})."
            )
        questions.append(
            CanaryQuestion(
                id=entry["id"],
                question=entry["question"],
                expected_outcome=outcome,
                expected_keywords=list(entry.get("expected_keywords", [])),
                must_not_appear=list(entry.get("must_not_appear", [])),
                expected_chunk_sources=list(entry.get("expected_chunk_sources", [])),
                category=entry["category"],
            )
        )
    return questions

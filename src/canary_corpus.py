"""Canary corpus — pure data inventory (issue #39).

50 curated questions designed against the live KB so every "answered" entry is
grounded in real content. Loaded once into a list of `CanaryQuestion` objects;
`canary_runner.py` replays them N=3 times per question through the current
pipeline, and `canary_drift.py` cross-references the corpus to compute drift
flags (branch routing, event_type, tool uptake on warranted questions, etc.).

Validation is a forcing function: `load_canaries()` re-resolves every
`expected_branch` against the live `branches.REGISTRY` at load time. A typo or
a removed branch fails on import rather than silently producing meaningless
drift signals at run time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from branches import REGISTRY
from interaction_log import EventType

DEFAULT_CORPUS_PATH = (
    Path(__file__).parent.parent / "data" / "canaries" / "corpus.json"
)


@dataclass(frozen=True)
class CanaryQuestion:
    """One curated canary entry. The full set lives in
    ``data/canaries/corpus.json``; the runner replays it N replicates per
    question through ``Pipeline.run`` and the drift detector reads the
    expected_* fields to compute drift kinds without LLM-as-judge.

    `expected_chunk_sources` / `expected_keywords` are corpus-side hints used
    by future drift extensions; v1 detectors lean on branch + event_type +
    tool_calls + chunk-set Jaccard rather than answer-text matching."""
    id: str
    question: str
    expected_branch: str
    expected_event_type: EventType
    expected_chunk_sources: list[str]
    expected_keywords: list[str]
    category: str
    requires_tool: bool


def load_canaries(path: Path = DEFAULT_CORPUS_PATH) -> list[CanaryQuestion]:
    """Parse corpus.json into a list of `CanaryQuestion`. Validates each
    entry's `expected_branch` against the live `branches.REGISTRY` —
    misspellings fail at load time, before any replay starts."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    questions: list[CanaryQuestion] = []
    for entry in raw:
        branch = entry["expected_branch"]
        if branch not in REGISTRY:
            raise ValueError(
                f"Canary {entry.get('id', '?')}: expected_branch={branch!r} "
                f"is not in branches.REGISTRY ({sorted(REGISTRY)})."
            )
        questions.append(
            CanaryQuestion(
                id=entry["id"],
                question=entry["question"],
                expected_branch=branch,
                expected_event_type=entry["expected_event_type"],
                expected_chunk_sources=list(entry.get("expected_chunk_sources", [])),
                expected_keywords=list(entry.get("expected_keywords", [])),
                category=entry["category"],
                requires_tool=bool(entry["requires_tool"]),
            )
        )
    return questions

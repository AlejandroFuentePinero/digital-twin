"""Canary corpus: pure data inventory (issue #39, recalibrated in #45 and #53).

50 curated questions designed against the live KB. Loaded once into a list of
`CanaryQuestion` objects; `canary_runner.py` replays them N=3 times per
question through the current pipeline, and `canary_judge.py` grades every
replicate's answer against the question's `expected_behaviour`.

Validation is a forcing function: `load_canaries()` refuses an entry with no
`expected_behaviour`, because the judge would have nothing to grade against.
Before #53 each entry carried `expected_outcome`, `expected_keywords` and
`must_not_appear`, matched by substring and by branch; the one-or-two
sentence description replaced all three.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORPUS_PATH = (
    Path(__file__).parent.parent / "data" / "canaries" / "corpus.json"
)


@dataclass(frozen=True)
class CanaryQuestion:
    """One curated canary entry. The full set lives in
    ``data/canaries/corpus.json``.

    `expected_behaviour` is one or two plain sentences stating the core point
    a correct answer gets across, with optional details marked "may".
    `expected_chunk_sources` stays descriptive for future retrieval checks."""
    id: str
    question: str
    expected_behaviour: str
    expected_chunk_sources: list[str]
    category: str


def load_canaries(path: Path = DEFAULT_CORPUS_PATH) -> list[CanaryQuestion]:
    """Parse corpus.json into a list of `CanaryQuestion`. An entry without an
    `expected_behaviour` fails at load time, before any replay starts."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    questions: list[CanaryQuestion] = []
    for entry in raw:
        behaviour = entry.get("expected_behaviour", "").strip()
        if not behaviour:
            raise ValueError(
                f"Canary {entry.get('id', '?')}: expected_behaviour is missing "
                "or empty; the judge has nothing to grade against."
            )
        questions.append(
            CanaryQuestion(
                id=entry["id"],
                question=entry["question"],
                expected_behaviour=behaviour,
                expected_chunk_sources=list(entry.get("expected_chunk_sources", [])),
                category=entry["category"],
            )
        )
    return questions

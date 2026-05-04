"""Lightweight KB section inventory — no ChromaDB / OpenAI imports.

`ingest.py` is the canonical embedder, but importing it pulls chromadb + openai
+ requires ``OPENAI_API_KEY`` at module load — too heavy for the dashboard.
This module mirrors `ingest.py`'s section-split rule (split markdown files on
``## `` boundaries, except SUMMARY/INDEX which stay un-split) so Sentinel's
Source coverage panel can enumerate every canonical section without booting
the embedder.

Drift is checked by `tests/test_kb_corpus.py` — the inventory must equal the
distinct ``(source_file, section_heading)`` pairs `ingest.load_chunks()` would
produce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

KB_PATH = Path(__file__).parent.parent / "data" / "knowledge_base"
UNSPLIT = {"SUMMARY", "INDEX"}
HEADING_RE = re.compile(r"^(#{2}) (.+)", re.MULTILINE)


@dataclass(frozen=True)
class Section:
    source_file: str
    section_heading: str


@dataclass(frozen=True)
class CoverageEntry:
    """One row in the Source coverage panel.

    `retrieval_count` is the number of times the section appears in any
    record's ``retrieved_chunks`` over the window. `off_canon` is True when a
    retrieved (file, section) pair doesn't appear in the canonical KB
    inventory — usually a stale embedding the operator forgot to re-ingest
    after deleting a section."""
    source_file: str
    section_heading: str
    retrieval_count: int
    off_canon: bool = False


def load_sections(kb_path: Path = KB_PATH) -> list[Section]:
    """All canonical ``(source_file, section_heading)`` pairs in the KB.

    Mirrors the split rule in ``ingest.split_on_headings``: split on ``## ``
    boundaries; the preamble (text before the first ``##``) gets the file
    stem as ``section_heading`` only if it has meaningful content (more
    than the H1 title and horizontal rules)."""
    sections: list[Section] = []
    for path in sorted(Path(kb_path).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if path.stem in UNSPLIT:
            sections.append(Section(path.name, path.stem))
            continue

        matches = [(m.start(), m.group(2)) for m in HEADING_RE.finditer(text)]
        if not matches:
            sections.append(Section(path.name, path.stem))
            continue

        preamble = text[: matches[0][0]].strip()
        meaningful = [
            l for l in preamble.splitlines()
            if l and not l.startswith("# ") and l.strip() != "---"
        ]
        if meaningful:
            sections.append(Section(path.name, path.stem))
        for _, heading in matches:
            sections.append(Section(path.name, heading))
    return sections


def compute_coverage(
    retrieved_chunks: list[dict],
    canonical: list[Section],
) -> list[CoverageEntry]:
    """Cross-reference `retrieved_chunks` against the canonical section list.

    `retrieved_chunks` is the flat list of every chunk that appeared in any
    record's `retrieved_chunks` field — the caller flattens across records
    and the window. Returns one entry per canonical section (with its
    retrieval count) plus one entry per off-canon retrieval (sections in
    the embeddings but not in current KB files — drift signal).

    Sort: never-retrieved canonical sections first (count=0, ascending by
    file/section), then the rest by ascending retrieval count, then
    off-canon entries last."""
    from collections import Counter

    counter: Counter[tuple[str, str]] = Counter()
    for chunk in retrieved_chunks:
        key = (chunk.get("source_file", ""), chunk.get("section_heading", ""))
        if key == ("", ""):
            continue
        counter[key] += 1

    canonical_keys = {(s.source_file, s.section_heading) for s in canonical}
    entries: list[CoverageEntry] = [
        CoverageEntry(
            source_file=s.source_file,
            section_heading=s.section_heading,
            retrieval_count=counter.get((s.source_file, s.section_heading), 0),
            off_canon=False,
        )
        for s in canonical
    ]
    for key, count in counter.items():
        if key not in canonical_keys:
            entries.append(CoverageEntry(
                source_file=key[0], section_heading=key[1],
                retrieval_count=count, off_canon=True,
            ))

    entries.sort(key=lambda e: (
        e.off_canon,           # off-canon last
        e.retrieval_count,     # ascending count (zero first)
        e.source_file, e.section_heading,
    ))
    return entries

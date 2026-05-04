"""Tests for the lightweight KB section inventory + coverage cross-reference."""

from pathlib import Path

import pytest

from kb_corpus import (
    CoverageEntry,
    Section,
    compute_coverage,
    load_sections,
)


# ---- load_sections ----------------------------------------------------------


def test_load_sections_returns_pairs_for_split_files(tmp_path: Path):
    """Files with ``## `` headings yield one Section per heading. The preamble
    contributes a section only when it has content beyond the H1 title."""
    f = tmp_path / "experience.md"
    f.write_text(
        "# Experience\n\n"
        "Some preamble paragraph that is meaningful.\n\n"
        "## Officeworks\n\nbody\n\n"
        "## Macquarie\n\nbody\n",
        encoding="utf-8",
    )
    sections = load_sections(tmp_path)

    assert Section("experience.md", "experience") in sections  # preamble survives
    assert Section("experience.md", "Officeworks") in sections
    assert Section("experience.md", "Macquarie") in sections
    assert len(sections) == 3


def test_load_sections_drops_empty_preamble(tmp_path: Path):
    """A file whose preamble is just the H1 title and a horizontal rule should
    not produce a stem-named section — that would double-count the body that
    starts at the first ``## ``."""
    f = tmp_path / "skills.md"
    f.write_text(
        "# Skills\n\n---\n\n"
        "## AI / LLM\n\nbody\n",
        encoding="utf-8",
    )
    sections = load_sections(tmp_path)
    assert Section("skills.md", "AI / LLM") in sections
    assert Section("skills.md", "skills") not in sections


def test_load_sections_keeps_unsplit_files_whole(tmp_path: Path):
    """SUMMARY and INDEX are stored as single un-split chunks (per ingest.py)
    so they appear once with the file stem as the section_heading."""
    (tmp_path / "SUMMARY.md").write_text(
        "## Heading inside SUMMARY\n\nbody\n", encoding="utf-8"
    )
    sections = load_sections(tmp_path)
    assert sections == [Section("SUMMARY.md", "SUMMARY")]


def test_load_sections_against_real_kb_returns_nonempty():
    """Smoke against the real ``data/knowledge_base`` — defends against an
    empty / wrong-path glob silently producing no sections."""
    sections = load_sections()
    assert len(sections) > 0
    # Every entry has both fields populated.
    for s in sections:
        assert s.source_file
        assert s.section_heading


# ---- compute_coverage -------------------------------------------------------


def test_compute_coverage_counts_retrievals_and_marks_never_retrieved():
    """Every canonical section appears in the result; sections never
    retrieved have count=0; those retrieved get the right count."""
    canonical = [
        Section("a.md", "Alpha"),
        Section("a.md", "Beta"),
        Section("b.md", "Gamma"),
    ]
    retrieved = [
        {"source_file": "a.md", "section_heading": "Alpha"},
        {"source_file": "a.md", "section_heading": "Alpha"},
        {"source_file": "b.md", "section_heading": "Gamma"},
    ]
    result = compute_coverage(retrieved, canonical)

    by_key = {(e.source_file, e.section_heading): e for e in result}
    assert by_key[("a.md", "Alpha")].retrieval_count == 2
    assert by_key[("a.md", "Beta")].retrieval_count == 0
    assert by_key[("b.md", "Gamma")].retrieval_count == 1
    # Never-retrieved sorts before retrieved ones.
    counts = [e.retrieval_count for e in result]
    assert counts == sorted(counts)


def test_compute_coverage_flags_off_canon_retrievals():
    """Retrieved chunks whose (file, section) pair doesn't appear in the
    canonical inventory get flagged as off_canon — drift signal for stale
    embeddings the operator forgot to re-ingest after a KB rewrite."""
    canonical = [Section("a.md", "Alpha")]
    retrieved = [
        {"source_file": "a.md", "section_heading": "Alpha"},
        {"source_file": "deleted.md", "section_heading": "Old section"},
    ]
    result = compute_coverage(retrieved, canonical)
    off = [e for e in result if e.off_canon]
    assert len(off) == 1
    assert off[0].source_file == "deleted.md"
    assert off[0].section_heading == "Old section"
    assert off[0].retrieval_count == 1
    # Off-canon entries sort *after* canonical ones.
    assert result[-1].off_canon is True


def test_compute_coverage_handles_empty_inputs():
    """Empty retrieved + empty canonical → empty result. Non-empty canonical
    + empty retrieved → all entries with count=0."""
    assert compute_coverage([], []) == []

    canonical = [Section("a.md", "Alpha")]
    result = compute_coverage([], canonical)
    assert len(result) == 1
    assert result[0].retrieval_count == 0
    assert result[0].off_canon is False

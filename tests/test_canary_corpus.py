"""Tests for the canary corpus loader (issue #39, recalibrated in #45 and #53)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from canary_corpus import CanaryQuestion, load_canaries


def test_load_canaries_returns_fifty_entries_against_real_corpus():
    """The shipped corpus has exactly 50 entries — the design contract from
    the issue's coverage matrix. Loading the real file is the smoke test."""
    questions = load_canaries()
    assert len(questions) == 50


def test_load_canaries_populates_every_required_field_for_every_entry():
    """Every entry has id, question, expected_behaviour, category. Smoke that
    the loader doesn't silently skip fields after the #53 corpus rewrite."""
    for q in load_canaries():
        assert q.id
        assert q.question
        assert q.expected_behaviour
        assert isinstance(q.expected_chunk_sources, list)
        assert q.category


def test_load_canaries_round_trips_a_minimal_entry(tmp_path: Path):
    """A single-entry corpus parses cleanly — defends against a refactor that
    quietly assumes >1 entries (e.g. when computing summary stats)."""
    one = tmp_path / "corpus.json"
    one.write_text(json.dumps([
        {
            "id": "C999",
            "question": "smoke",
            "expected_behaviour": "Says smoke.",
            "expected_chunk_sources": ["profile.md"],
            "category": "smoke",
        }
    ]))
    [q] = load_canaries(one)
    assert q == CanaryQuestion(
        id="C999",
        question="smoke",
        expected_behaviour="Says smoke.",
        expected_chunk_sources=["profile.md"],
        category="smoke",
    )


def test_every_real_corpus_entry_describes_its_expected_behaviour():
    """Issue #53: the judge grades each answer against this description, so
    an entry without one cannot be judged."""
    for q in load_canaries():
        assert q.expected_behaviour.strip(), q.id


def test_load_canaries_rejects_an_entry_without_expected_behaviour(tmp_path: Path):
    """A blank expected_behaviour fails at load time, naming the entry."""
    bad = tmp_path / "corpus.json"
    bad.write_text(json.dumps([
        {
            "id": "C001",
            "question": "q",
            "expected_behaviour": "  ",
            "expected_chunk_sources": [],
            "category": "x",
        }
    ]))
    with pytest.raises(ValueError, match="C001"):
        load_canaries(bad)

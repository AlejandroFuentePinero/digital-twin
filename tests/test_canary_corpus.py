"""Tests for the canary corpus loader (issue #39)."""

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
    """Every entry has id, question, branch, event_type, category, and a
    bool requires_tool. Smoke that the loader doesn't silently skip fields."""
    for q in load_canaries():
        assert q.id
        assert q.question
        assert q.expected_branch
        assert q.expected_event_type
        assert q.category
        assert isinstance(q.requires_tool, bool)


def test_load_canaries_rejects_unknown_expected_branch(tmp_path: Path):
    """Forcing function: a typo in `expected_branch` (or a removed branch)
    fails at load time, before any replay starts. The drift detector relies
    on the branch comparing equal to a real registry key."""
    bad = tmp_path / "corpus.json"
    bad.write_text(json.dumps([
        {
            "id": "C001",
            "question": "q",
            "expected_branch": "MADE_UP_BRANCH",
            "expected_event_type": "answered",
            "expected_chunk_sources": [],
            "expected_keywords": [],
            "category": "x",
            "requires_tool": False,
        }
    ]))
    with pytest.raises(ValueError, match="MADE_UP_BRANCH"):
        load_canaries(bad)


def test_load_canaries_round_trips_a_minimal_entry(tmp_path: Path):
    """A single-entry corpus parses cleanly — defends against a refactor that
    quietly assumes >1 entries (e.g. when computing summary stats)."""
    one = tmp_path / "corpus.json"
    one.write_text(json.dumps([
        {
            "id": "C999",
            "question": "smoke",
            "expected_branch": "GENERIC",
            "expected_event_type": "answered",
            "expected_chunk_sources": ["profile.md"],
            "expected_keywords": ["alpha"],
            "category": "smoke",
            "requires_tool": False,
        }
    ]))
    [q] = load_canaries(one)
    assert q == CanaryQuestion(
        id="C999",
        question="smoke",
        expected_branch="GENERIC",
        expected_event_type="answered",
        expected_chunk_sources=["profile.md"],
        expected_keywords=["alpha"],
        category="smoke",
        requires_tool=False,
    )

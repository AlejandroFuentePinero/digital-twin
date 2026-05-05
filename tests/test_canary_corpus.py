"""Tests for the canary corpus loader (issue #39, recalibrated in #45)."""

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
    """Every entry has id, question, expected_outcome, expected_keywords,
    must_not_appear, category. Smoke that the loader doesn't silently skip
    fields after the #45 corpus relabel."""
    valid_outcomes = {
        "answered_with_substance", "gap_acknowledged",
        "out_of_scope_redirect", "refused",
    }
    for q in load_canaries():
        assert q.id
        assert q.question
        assert q.expected_outcome in valid_outcomes
        assert isinstance(q.expected_keywords, list)
        assert isinstance(q.must_not_appear, list)
        assert q.category


def test_load_canaries_rejects_unknown_expected_outcome(tmp_path: Path):
    """Forcing function: a typo in `expected_outcome` (or a removed bucket)
    fails at load time, before any replay starts. The drift detector relies
    on the outcome comparing equal to one of the four canonical buckets."""
    bad = tmp_path / "corpus.json"
    bad.write_text(json.dumps([
        {
            "id": "C001",
            "question": "q",
            "expected_outcome": "MADE_UP_BUCKET",
            "expected_keywords": [],
            "must_not_appear": [],
            "expected_chunk_sources": [],
            "category": "x",
        }
    ]))
    with pytest.raises(ValueError, match="MADE_UP_BUCKET"):
        load_canaries(bad)


def test_load_canaries_round_trips_a_minimal_entry(tmp_path: Path):
    """A single-entry corpus parses cleanly — defends against a refactor that
    quietly assumes >1 entries (e.g. when computing summary stats)."""
    one = tmp_path / "corpus.json"
    one.write_text(json.dumps([
        {
            "id": "C999",
            "question": "smoke",
            "expected_outcome": "answered_with_substance",
            "expected_keywords": ["alpha"],
            "must_not_appear": ["beta"],
            "expected_chunk_sources": ["profile.md"],
            "category": "smoke",
        }
    ]))
    [q] = load_canaries(one)
    assert q == CanaryQuestion(
        id="C999",
        question="smoke",
        expected_outcome="answered_with_substance",
        expected_keywords=["alpha"],
        must_not_appear=["beta"],
        expected_chunk_sources=["profile.md"],
        category="smoke",
    )

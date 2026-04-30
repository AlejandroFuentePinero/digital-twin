"""
Tests for logger.py.

Strategy:
- All tests redirect LOG_PATH to a tmp_path so nothing touches the real log
- Verify: JSONL is valid, all fields present, append behaviour, knew_answer detection
"""

import json
from pathlib import Path

import pytest

import logger as logger_module
from logger import log_interaction


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    log_file = tmp_path / "interactions.jsonl"
    monkeypatch.setattr(logger_module, "LOG_PATH", log_file)
    return log_file


def read_entries(tmp_log: Path) -> list[dict]:
    return [json.loads(line) for line in tmp_log.read_text().splitlines()]


# ---------------------------------------------------------------------------
# Field presence and types
# ---------------------------------------------------------------------------


def test_log_interaction_writes_all_fields(tmp_log):
    """Every required field is present in the persisted JSONL entry."""
    log_interaction("What are his skills?", "He knows Python.", True, True, 0)
    entry = read_entries(tmp_log)[0]

    assert "timestamp" in entry
    assert "session_id" in entry
    assert "question" in entry
    assert "answer" in entry
    assert "is_acceptable" in entry
    assert "knew_answer" in entry
    assert "retry_count" in entry


def test_log_interaction_stores_correct_values(tmp_log):
    """Field values round-trip exactly as supplied to log_interaction."""
    log_interaction("What is his PhD topic?", "Tropical ecology.", True, True, 0, "sess-1")
    entry = read_entries(tmp_log)[0]

    assert entry["question"] == "What is his PhD topic?"
    assert entry["answer"] == "Tropical ecology."
    assert entry["is_acceptable"] is True
    assert entry["knew_answer"] is True
    assert entry["retry_count"] == 0
    assert entry["session_id"] == "sess-1"


def test_log_interaction_session_id_none_when_omitted(tmp_log):
    """session_id is recorded as null when caller does not supply one."""
    log_interaction("q", "a", True, True, 0)
    entry = read_entries(tmp_log)[0]
    assert entry["session_id"] is None


def test_log_interaction_timestamp_is_iso_format(tmp_log):
    """Timestamps are ISO 8601 — sortable and timezone-aware."""
    log_interaction("q", "a", True, True, 0)
    entry = read_entries(tmp_log)[0]
    assert "T" in entry["timestamp"]


# ---------------------------------------------------------------------------
# knew_answer flag
# ---------------------------------------------------------------------------


def test_knew_answer_true_when_gap_phrase_absent(tmp_log):
    """A confident answer logs knew_answer=True."""
    log_interaction("q", "He has a PhD in ecology.", True, True, 0)
    assert read_entries(tmp_log)[0]["knew_answer"] is True


def test_knew_answer_false_when_gap_phrase_present(tmp_log):
    """A gap-phrase answer logs knew_answer=False."""
    log_interaction("q", "I don't have that information in my knowledge base.", True, False, 0)
    assert read_entries(tmp_log)[0]["knew_answer"] is False


# ---------------------------------------------------------------------------
# Append behaviour
# ---------------------------------------------------------------------------


def test_each_call_appends_a_new_line(tmp_log):
    """Successive calls append rather than overwrite — log grows monotonically."""
    log_interaction("q1", "a1", True, True, 0)
    log_interaction("q2", "a2", False, False, 2)

    entries = read_entries(tmp_log)
    assert len(entries) == 2
    assert entries[0]["question"] == "q1"
    assert entries[1]["question"] == "q2"


def test_each_line_is_valid_json(tmp_log):
    """The log is strict JSONL — every line parses on its own."""
    log_interaction("q1", "a1", True, True, 0)
    log_interaction("q2", "a2", False, True, 1, "s")

    for line in tmp_log.read_text().splitlines():
        json.loads(line)


def test_log_creates_parent_directory_if_missing(tmp_path, monkeypatch):
    """log_interaction creates missing parent directories rather than crashing."""
    nested = tmp_path / "new_dir" / "interactions.jsonl"
    monkeypatch.setattr(logger_module, "LOG_PATH", nested)

    log_interaction("q", "a", True, True, 0)

    assert nested.exists()


# ---------------------------------------------------------------------------
# retry_count and is_acceptable
# ---------------------------------------------------------------------------


def test_retry_count_zero_on_first_attempt(tmp_log):
    """retry_count=0 means the first generation passed the guardrail."""
    log_interaction("q", "a", True, True, 0)
    assert read_entries(tmp_log)[0]["retry_count"] == 0


def test_retry_count_reflects_number_of_retries(tmp_log):
    """retry_count is stored verbatim — used downstream by Sentinel diagnostics."""
    log_interaction("q", "a", True, True, 2)
    assert read_entries(tmp_log)[0]["retry_count"] == 2


def test_is_acceptable_false_stored_correctly(tmp_log):
    """is_acceptable=False (canned refusal) round-trips as False, not truthy."""
    log_interaction("q", "canned refusal", False, True, 2)
    assert read_entries(tmp_log)[0]["is_acceptable"] is False

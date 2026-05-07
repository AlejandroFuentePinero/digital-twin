"""Pure-function tests for the schema migration layer (issue #48 / Phase 6 slice C).

The handler runs upstream of `InteractionRecord.model_validate` in
`log_reader._parse_jsonl_to_records`, so it must (a) raise a clear,
catchable error on records missing a required field, (b) fill in any
optional fields that were added in later schema bumps with their
None-defaults, and (c) pass future-version records through unchanged
with a warning so a producer ahead of the reader can't crash the
dashboard.
"""

from __future__ import annotations

import logging

import pytest

from interaction_log import SCHEMA_VERSION
from schema_migrations import (
    MissingRequiredFieldError,
    SchemaVersionHandler,
)


def _v3_full_record() -> dict:
    """A record with every v3+ field populated — used as a baseline for
    per-version field stripping in the tests below."""
    return {
        "schema_version": "3",
        "timestamp": "2026-05-07T12:00:00+00:00",
        "session_id": "sess-abc",
        "turn_index": 0,
        "question": "Tell me about your background.",
        "event_type": "answered",
        "branch": "GENERIC",
        "classifier_labels": ["GENERIC"],
        "classification_confidence": 1.0,
        "attempts": [{"answer": "Hi.", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [{"source_file": "identity.md", "section_heading": "identity"}],
        "tool_calls": [],
        "latency_ms": {"classifier": 100, "retrieval": 200, "generation": 800, "guardrail": 400, "total": 1500},
        "knew_answer": True,
        "contact_offered": False,
        "contact_provided": False,
        "git_sha": "deadbeef",
        "model_id": "gpt-4.1",
        "temperature": 1.0,
        "prompt_hash": "abc123def456",
        "is_canary": False,
        "replicate_index": None,
        "run_id": None,
    }


def test_v1_record_migrates_with_repro_canary_and_classifier_labels_filled():
    """A v1-shape record (pre-#15 / #37 / #39) lacks classifier_labels,
    reproducibility, and canary fields. After migration every later
    optional field carries its default."""
    v1 = _v3_full_record() | {"schema_version": "1"}
    for key in (
        "classifier_labels",
        "git_sha",
        "model_id",
        "temperature",
        "prompt_hash",
        "is_canary",
        "replicate_index",
        "run_id",
    ):
        v1.pop(key, None)

    out = SchemaVersionHandler(v1)

    assert out["schema_version"] == "1", "on-disk stamp preserved"
    assert out["classifier_labels"] == []
    assert out["git_sha"] is None
    assert out["model_id"] is None
    assert out["temperature"] is None
    assert out["prompt_hash"] is None
    assert out["is_canary"] is False
    assert out["replicate_index"] is None
    assert out["run_id"] is None


def test_v2_record_migrates_with_canary_fields_filled():
    """A v2-shape record (post-#37, pre-#39) has reproducibility but no
    canary fields. Canary defaults must be applied."""
    v2 = _v3_full_record() | {"schema_version": "2"}
    for key in ("is_canary", "replicate_index", "run_id"):
        v2.pop(key, None)

    out = SchemaVersionHandler(v2)

    assert out["schema_version"] == "2"
    assert out["is_canary"] is False
    assert out["replicate_index"] is None
    assert out["run_id"] is None
    # Reproducibility fields untouched (already present on v2 records)
    assert out["git_sha"] == "deadbeef"
    assert out["model_id"] == "gpt-4.1"


def test_v3_full_record_is_idempotent():
    """A record already at v3 with every optional populated must round-trip
    unchanged — no spurious overwrites."""
    v3 = _v3_full_record()
    snapshot = dict(v3)

    out = SchemaVersionHandler(v3)

    assert out == snapshot, "fully-populated v3 record must not be mutated"


def test_missing_required_field_raises_with_field_session_and_turn():
    """The error message must name the missing field AND the record's
    session_id + turn_index so triage can locate it in the log."""
    bad = _v3_full_record()
    bad.pop("timestamp")  # required across every schema version

    with pytest.raises(MissingRequiredFieldError) as exc_info:
        SchemaVersionHandler(bad)

    msg = str(exc_info.value)
    assert "timestamp" in msg
    assert "sess-abc" in msg
    assert "turn_index" in msg or str(bad["turn_index"]) in msg


def test_missing_required_error_is_a_value_error():
    """The reader's existing `except (json.JSONDecodeError, ValueError)`
    must catch this — extending ValueError preserves the resilience
    pattern (skip-with-warning) without a new try/except."""
    bad = _v3_full_record()
    bad.pop("knew_answer")

    with pytest.raises(ValueError):
        SchemaVersionHandler(bad)


def test_future_schema_version_passes_through_unchanged_with_warning(caplog):
    """A producer running ahead of the reader (schema_version > target)
    must not crash the dashboard. The handler logs a warning and returns
    the record byte-identical so pydantic decides whether the extra/missing
    fields validate."""
    future = _v3_full_record() | {"schema_version": "5", "future_field": "ignored"}
    snapshot = dict(future)

    with caplog.at_level(logging.WARNING, logger="schema_migrations"):
        out = SchemaVersionHandler(future, target_version=SCHEMA_VERSION)

    assert out == snapshot, "future-version records pass through unchanged"
    assert any(
        "schema_version" in rec.message and "5" in rec.message
        for rec in caplog.records
    ), "a warning must name the unrecognised schema_version"


def test_target_version_default_tracks_current_schema_version_constant():
    """The default target version is the canonical SCHEMA_VERSION constant
    so a future schema bump is a one-line change in interaction_log.py."""
    v1 = _v3_full_record() | {"schema_version": "1"}
    for key in ("git_sha", "is_canary", "replicate_index", "run_id"):
        v1.pop(key, None)

    out_default = SchemaVersionHandler(v1)
    out_explicit = SchemaVersionHandler(v1, target_version=SCHEMA_VERSION)

    assert out_default == out_explicit


def test_handler_does_not_mutate_input_record():
    """The handler returns a new dict — callers passing a record they
    don't own (e.g. a parsed JSONL line referenced elsewhere) must see
    no in-place mutation."""
    v1 = _v3_full_record() | {"schema_version": "1"}
    v1.pop("is_canary", None)
    snapshot = dict(v1)

    SchemaVersionHandler(v1)

    assert v1 == snapshot, "input record must not be mutated in place"

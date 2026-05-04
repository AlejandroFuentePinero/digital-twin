import json
from datetime import datetime, timedelta, timezone

from pathlib import Path

import pytest

from interaction_log import DEFAULT_LOG_PATH, InteractionRecord
from log_reader import HFReader, LocalReader


def _record(timestamp: str = "2026-05-01T12:00:00+00:00", turn_index: int = 0) -> dict:
    return {
        "schema_version": "1",
        "timestamp": timestamp,
        "session_id": "sess-abc",
        "turn_index": turn_index,
        "question": "Tell me about your background.",
        "event_type": "answered",
        "branch": "GENERIC",
        "classification_confidence": 1.0,
        "attempts": [{"answer": "Hi.", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [{"source_file": "identity.md", "section_heading": "identity"}],
        "tool_calls": [],
        "latency_ms": {"classifier": 100, "retrieval": 200, "generation": 800, "guardrail": 400, "total": 1500},
        "knew_answer": True,
        "contact_offered": False,
        "contact_provided": False,
    }


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_read_returns_typed_interaction_records(tmp_path):
    """LocalReader.read() parses each JSONL line into a typed InteractionRecord."""
    log_path = tmp_path / "interactions.jsonl"
    _write_jsonl(log_path, [_record()])

    out = LocalReader(log_path).read()

    assert len(out) == 1
    assert isinstance(out[0], InteractionRecord)
    assert out[0].question == "Tell me about your background."
    assert out[0].branch == "GENERIC"


def test_read_returns_empty_list_when_file_does_not_exist(tmp_path):
    """LocalReader on a fresh path with no log file yet returns [] instead of raising."""
    out = LocalReader(tmp_path / "does_not_exist.jsonl").read()
    assert out == []


def test_read_returns_records_most_recent_first(tmp_path):
    """LocalReader.read() orders records by timestamp descending regardless of file order."""
    log_path = tmp_path / "interactions.jsonl"
    _write_jsonl(
        log_path,
        [
            _record(timestamp="2026-04-01T00:00:00+00:00", turn_index=1),
            _record(timestamp="2026-06-01T00:00:00+00:00", turn_index=3),
            _record(timestamp="2026-05-01T00:00:00+00:00", turn_index=2),
        ],
    )

    out = LocalReader(log_path).read()

    assert [r.turn_index for r in out] == [3, 2, 1]


def test_read_with_days_filter_excludes_older_records(tmp_path):
    """LocalReader.read(days=N) returns only records within the last N days from now."""
    log_path = tmp_path / "interactions.jsonl"
    now = datetime.now(timezone.utc)
    _write_jsonl(
        log_path,
        [
            _record(timestamp=(now - timedelta(days=30)).isoformat(), turn_index=0),  # outside
            _record(timestamp=(now - timedelta(days=3)).isoformat(), turn_index=1),  # inside
            _record(timestamp=(now - timedelta(hours=1)).isoformat(), turn_index=2),  # inside
        ],
    )

    out = LocalReader(log_path).read(days=7)

    assert sorted(r.turn_index for r in out) == [1, 2]


def test_read_skips_malformed_line_and_logs_warning(tmp_path, caplog):
    """A line that fails to parse is skipped, a warning is logged, and surrounding valid records still come through."""
    import logging

    log_path = tmp_path / "interactions.jsonl"
    valid = json.dumps(_record(turn_index=0))
    log_path.write_text(valid + "\n" + "{not valid json\n" + json.dumps(_record(turn_index=2)) + "\n")

    with caplog.at_level(logging.WARNING, logger="log_reader"):
        out = LocalReader(log_path).read()

    assert sorted(r.turn_index for r in out) == [0, 2]
    assert any("malformed" in rec.message.lower() or "skipping" in rec.message.lower() for rec in caplog.records)


@pytest.mark.skipif(not Path(DEFAULT_LOG_PATH).exists(), reason="No real log file present")
def test_local_reader_parses_real_interactions_log_cleanly():
    """Pointed at the live data/logs/interactions.jsonl, LocalReader returns >=1 record without errors."""
    out = LocalReader().read()
    assert len(out) >= 1
    assert all(isinstance(r, InteractionRecord) for r in out)


def test_hf_reader_raises_not_implemented_until_phase_6(tmp_path):
    """HFReader is a Phase 6 stub per ADR-0002 — calling read() must surface that explicitly."""
    with pytest.raises(NotImplementedError, match="Phase 6"):
        HFReader().read()


def test_read_tolerates_records_missing_optional_fields(tmp_path):
    """A record written under an older schema (missing optional fields) parses with defaults applied."""
    log_path = tmp_path / "interactions.jsonl"
    legacy = _record()
    for key in ("tool_calls", "contact_offered", "contact_provided", "schema_version", "classifier_labels"):
        legacy.pop(key, None)
    _write_jsonl(log_path, [legacy])

    out = LocalReader(log_path).read()

    assert len(out) == 1
    assert out[0].tool_calls == []
    assert out[0].contact_offered is False
    assert out[0].contact_provided is False
    # A record that omits schema_version inherits the current default —
    # bumped to v4 in #42 (producer-side classifier emits all four EventType
    # values). Reader and writer share the SCHEMA_VERSION constant.
    from interaction_log import SCHEMA_VERSION
    assert out[0].schema_version == SCHEMA_VERSION
    assert out[0].classifier_labels == []


def test_read_tolerates_v1_records_lacking_reproducibility_fields(tmp_path):
    """Legacy v1 records (the existing 85+ live records pre-issue-#37) lack git_sha,
    model_id, temperature, and prompt_hash. LocalReader must still parse them with
    None defaults — schema-skew tolerance per issue #37 acceptance criteria."""
    log_path = tmp_path / "interactions.jsonl"
    legacy_v1 = _record() | {"schema_version": "1"}
    # The four new fields are absent on v1 records — never written.
    for key in ("git_sha", "model_id", "temperature", "prompt_hash"):
        legacy_v1.pop(key, None)
    _write_jsonl(log_path, [legacy_v1])

    out = LocalReader(log_path).read()

    assert len(out) == 1
    assert out[0].schema_version == "1", "explicit v1 stamp preserved"
    assert out[0].git_sha is None
    assert out[0].model_id is None
    assert out[0].temperature is None
    assert out[0].prompt_hash is None


def test_read_tolerates_pre_issue_39_records_lacking_canary_fields(tmp_path):
    """Forcing function for the live log: the 99+ records on disk pre-issue-#39
    have no `is_canary` / `run_id` / `replicate_index` keys at all. LocalReader
    must parse them with `is_canary=False`, `run_id=None`, `replicate_index=None`
    so they continue to flow through Sentinel's live tabs (which filter
    `is_canary=True`) without backfill."""
    log_path = tmp_path / "interactions.jsonl"
    legacy = _record() | {"schema_version": "2"}
    # The three canary fields are absent on pre-#39 records — never written.
    for key in ("is_canary", "run_id", "replicate_index"):
        legacy.pop(key, None)
    _write_jsonl(log_path, [legacy])

    out = LocalReader(log_path).read()

    assert len(out) == 1
    assert out[0].is_canary is False, (
        "legacy records must default to is_canary=False so the live tabs see them"
    )
    assert out[0].run_id is None
    assert out[0].replicate_index is None
    assert out[0].schema_version == "2", "explicit v2 stamp preserved"

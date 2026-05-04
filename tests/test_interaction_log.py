import pytest

from interaction_log import LogReader, LogWriter, compute_prompt_hash


def _full_record(timestamp: str = "2026-05-01T12:00:00+00:00") -> dict:
    """Return a fully-populated record matching the issue #13 schema."""
    return {
        "timestamp": timestamp,
        "session_id": "sess-abc",
        "turn_index": 0,
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


def test_append_and_read_all_round_trip(tmp_path):
    """A record written by LogWriter.append round-trips back through LogReader.read_all."""
    log_path = tmp_path / "interactions.jsonl"
    record = _full_record()
    LogWriter(log_path).append(record)
    out = LogReader(log_path).read_all()
    assert len(out) == 1
    assert out[0]["question"] == "Tell me about your background."
    assert out[0]["branch"] == "GENERIC"


def test_append_populates_default_fields_when_caller_omits_them(tmp_path):
    """tool_calls=[], contact_offered=False, contact_provided=False, schema_version='2' are present even when caller didn't set them."""
    log_path = tmp_path / "interactions.jsonl"
    minimal = _full_record()
    for key in ("tool_calls", "contact_offered", "contact_provided", "schema_version"):
        minimal.pop(key, None)
    LogWriter(log_path).append(minimal)
    record = LogReader(log_path).read_all()[0]
    assert record["tool_calls"] == []
    assert record["contact_offered"] is False
    assert record["contact_provided"] is False
    assert record["schema_version"] == "3"


def test_append_raises_on_missing_required_fields(tmp_path):
    """A record missing required fields (e.g. session_id) is rejected by Pydantic validation."""
    log_path = tmp_path / "interactions.jsonl"
    incomplete = _full_record()
    del incomplete["session_id"]
    with pytest.raises(Exception):  # Pydantic's ValidationError
        LogWriter(log_path).append(incomplete)
    # File should not be created on validation failure
    assert not log_path.exists()


def test_append_writes_jsonl_with_one_record_per_line(tmp_path):
    """Three appends produce a file with three newline-separated lines, each independently parseable as JSON."""
    import json as _json

    log_path = tmp_path / "interactions.jsonl"
    writer = LogWriter(log_path)
    for i in range(3):
        writer.append(_full_record() | {"turn_index": i})

    raw = log_path.read_text()
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 3
    parsed = [_json.loads(ln) for ln in lines]
    assert [r["turn_index"] for r in parsed] == [0, 1, 2]


def test_read_since_returns_records_at_or_after_the_cutoff(tmp_path):
    """read_since('t2') returns the t2 record and everything after, but not the earlier t1 record."""
    log_path = tmp_path / "interactions.jsonl"
    writer = LogWriter(log_path)
    writer.append(_full_record(timestamp="2026-04-01T00:00:00+00:00") | {"turn_index": 1})
    writer.append(_full_record(timestamp="2026-05-01T00:00:00+00:00") | {"turn_index": 2})
    writer.append(_full_record(timestamp="2026-06-01T00:00:00+00:00") | {"turn_index": 3})

    after_may = LogReader(log_path).read_since("2026-05-01T00:00:00+00:00")
    assert [r["turn_index"] for r in after_may] == [2, 3]


def test_read_all_returns_empty_list_when_log_does_not_exist(tmp_path):
    """LogReader on a fresh path with no log file yet returns [] instead of raising."""
    out = LogReader(tmp_path / "does_not_exist.jsonl").read_all()
    assert out == []


def test_schema_version_defaults_to_v2_with_reproducibility_fields(tmp_path):
    """A new record (no caller-provided schema fields) carries schema_version='2' and
    the four reproducibility fields (git_sha, model_id, temperature, prompt_hash)
    default to None — issue #37 schema bump."""
    log_path = tmp_path / "interactions.jsonl"
    LogWriter(log_path).append(_full_record())
    record = LogReader(log_path).read_all()[0]
    assert record["schema_version"] == "3"
    assert record["git_sha"] is None
    assert record["model_id"] is None
    assert record["temperature"] is None
    assert record["prompt_hash"] is None


def test_compute_prompt_hash_is_deterministic_and_12_hex_chars():
    """compute_prompt_hash(system, user) returns a 12-char hex SHA-256 prefix.
    Same inputs → same hash; any change in either → different hash. Core
    reproducibility guarantee for issue #37: 'same question, different rule
    set' is distinguishable at log level."""
    h1 = compute_prompt_hash("system A", "user A")
    h2 = compute_prompt_hash("system A", "user A")
    assert h1 == h2, "identical inputs must produce identical hashes"
    assert len(h1) == 12 and all(c in "0123456789abcdef" for c in h1)
    assert compute_prompt_hash("system B", "user A") != h1, "system change must change hash"
    assert compute_prompt_hash("system A", "user B") != h1, "user change must change hash"


def test_canary_fields_default_to_live_record_shape_and_round_trip_when_set(tmp_path):
    """Schema v3 (#39): is_canary defaults False, replicate_index + run_id default
    None — so legacy v2 records still parse. When a canary writer populates them
    they round-trip through writer/reader."""
    log_path = tmp_path / "interactions.jsonl"
    LogWriter(log_path).append(_full_record())
    live = LogReader(log_path).read_all()[0]
    assert live["is_canary"] is False
    assert live["replicate_index"] is None
    assert live["run_id"] is None

    canary_log = tmp_path / "canary.jsonl"
    canary = _full_record() | {
        "is_canary": True,
        "replicate_index": 2,
        "run_id": "run-2026-05-04-abc",
    }
    LogWriter(canary_log).append(canary)
    out = LogReader(canary_log).read_all()[0]
    assert out["is_canary"] is True
    assert out["replicate_index"] == 2
    assert out["run_id"] == "run-2026-05-04-abc"


def test_record_round_trips_reproducibility_fields_when_caller_populates_them(tmp_path):
    """git_sha, model_id, temperature, prompt_hash round-trip through writer/reader."""
    log_path = tmp_path / "interactions.jsonl"
    record = _full_record() | {
        "git_sha": "deadbeef1234",
        "model_id": "openai/gpt-4.1",
        "temperature": 0.7,
        "prompt_hash": "abcdef012345",
    }
    LogWriter(log_path).append(record)
    out = LogReader(log_path).read_all()[0]
    assert out["git_sha"] == "deadbeef1234"
    assert out["model_id"] == "openai/gpt-4.1"
    assert out["temperature"] == 0.7
    assert out["prompt_hash"] == "abcdef012345"

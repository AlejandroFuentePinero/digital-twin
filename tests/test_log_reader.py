import json
from datetime import datetime, timedelta, timezone

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from interaction_log import DEFAULT_LOG_PATH, InteractionRecord
from log_reader import HFLogReader, LocalReader, make_log_reader


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


def _hf_api_for_reader(files_by_path: dict[str, list[dict]]) -> MagicMock:
    """A MagicMock standing in for ``huggingface_hub.HfApi`` for the
    reader path.

    ``files_by_path`` maps ``logs/YYYY-MM-DD.jsonl`` → list of records;
    ``list_repo_files`` returns the keys, ``hf_hub_download`` writes the
    matching value to a temp file and returns its path."""
    import tempfile

    api = MagicMock()
    api.list_repo_files = MagicMock(return_value=list(files_by_path.keys()))

    def fake_download(*, repo_id, filename, repo_type):  # noqa: ARG001
        records = files_by_path[filename]
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.close()
        return f.name

    api.hf_hub_download = MagicMock(side_effect=fake_download)
    return api


def test_hf_log_reader_downloads_and_parses_per_day_files(tmp_path):
    files = {
        "logs/2026-05-06.jsonl": [_record(timestamp="2026-05-06T10:00:00+00:00", turn_index=1)],
        "logs/2026-05-07.jsonl": [_record(timestamp="2026-05-07T10:00:00+00:00", turn_index=2)],
    }
    api = _hf_api_for_reader(files)

    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()

    assert len(out) == 2
    assert all(isinstance(r, InteractionRecord) for r in out)
    assert sorted(r.turn_index for r in out) == [1, 2]


def test_hf_log_reader_dedupes_by_session_turn_run_and_replicate(tmp_path):
    """Reader-side dedup is the slice's single dedup choke point — a
    retried-after-ambiguous-failure flush can produce the same record
    twice. The key is
    ``(session_id, turn_index, run_id, replicate_index, timestamp)``;
    canary fields default ``None`` for live records."""
    duplicate_live = _record(timestamp="2026-05-07T10:00:00+00:00", turn_index=0)
    files = {
        "logs/2026-05-07.jsonl": [
            duplicate_live,
            duplicate_live,  # exact replay → same key → collapses
            _record(timestamp="2026-05-07T11:00:00+00:00", turn_index=1),
        ]
    }
    api = _hf_api_for_reader(files)

    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()

    assert sorted(r.turn_index for r in out) == [0, 1], "exact duplicates collapse"


def test_hf_log_reader_keeps_distinct_records_sharing_session_and_turn(tmp_path):
    """Two records with the same ``(session_id, turn_index)`` but different
    timestamps are distinct interactions, not flush-replay duplicates —
    e.g. multiple visitors who shared a default ``gr.State`` UUID before
    clicking 'New conversation'. Including timestamp in the dedup key
    keeps both."""
    files = {
        "logs/2026-05-07.jsonl": [
            _record(timestamp="2026-05-07T03:21:10+00:00", turn_index=1),
            _record(timestamp="2026-05-07T05:11:27+00:00", turn_index=1),
            _record(timestamp="2026-05-07T06:30:12+00:00", turn_index=1),
        ]
    }
    api = _hf_api_for_reader(files)

    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()

    assert len(out) == 3, "distinct timestamps = distinct interactions, kept verbatim"


def test_hf_log_reader_treats_canary_replicates_as_distinct(tmp_path):
    """Two canary records with the same session/turn but different
    ``replicate_index`` are NOT duplicates — replicates are the unit
    of the canary corpus, not a flush retry."""
    base = _record(timestamp="2026-05-07T10:00:00+00:00", turn_index=0)
    files = {
        "logs/2026-05-07.jsonl": [
            base | {"is_canary": True, "run_id": "r-1", "replicate_index": 0},
            base | {"is_canary": True, "run_id": "r-1", "replicate_index": 1},
            base | {"is_canary": True, "run_id": "r-1", "replicate_index": 2},
        ]
    }
    api = _hf_api_for_reader(files)

    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()
    assert sorted(r.replicate_index for r in out) == [0, 1, 2]


def test_hf_log_reader_returns_records_most_recent_first(tmp_path):
    files = {
        "logs/2026-05-05.jsonl": [_record(timestamp="2026-05-05T10:00:00+00:00", turn_index=1)],
        "logs/2026-05-07.jsonl": [_record(timestamp="2026-05-07T10:00:00+00:00", turn_index=3)],
        "logs/2026-05-06.jsonl": [_record(timestamp="2026-05-06T10:00:00+00:00", turn_index=2)],
    }
    api = _hf_api_for_reader(files)

    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()
    assert [r.turn_index for r in out] == [3, 2, 1]


def test_hf_log_reader_with_days_filter_only_downloads_in_window(tmp_path):
    """The days filter prunes by file name (each file is one UTC day) so
    files outside the window are never downloaded."""
    today = datetime.now(timezone.utc).date()
    in_window = (today - timedelta(days=2)).isoformat()
    out_window = (today - timedelta(days=30)).isoformat()
    files = {
        f"logs/{out_window}.jsonl": [
            _record(timestamp=f"{out_window}T10:00:00+00:00", turn_index=99)
        ],
        f"logs/{in_window}.jsonl": [
            _record(timestamp=f"{in_window}T10:00:00+00:00", turn_index=1)
        ],
    }
    api = _hf_api_for_reader(files)

    out = HFLogReader(repo_id="ignored/test", hf_api=api).read(days=7)

    assert [r.turn_index for r in out] == [1]
    downloaded = [c.kwargs["filename"] for c in api.hf_hub_download.call_args_list]
    assert all(in_window in n for n in downloaded), (
        f"out-of-window files must not be downloaded; got {downloaded}"
    )


def test_hf_log_reader_returns_empty_list_when_repo_has_no_log_files(tmp_path):
    api = _hf_api_for_reader({"README.md": []})
    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()
    assert out == []


def test_hf_log_reader_skips_non_log_paths_in_repo_listing(tmp_path):
    """``list_repo_files`` returns everything in the repo (README.md,
    ``.gitattributes``, etc.) — only ``logs/*.jsonl`` are interaction
    records."""
    files = {
        "README.md": [],
        ".gitattributes": [],
        "logs/2026-05-07.jsonl": [_record(timestamp="2026-05-07T10:00:00+00:00", turn_index=1)],
    }
    api = _hf_api_for_reader(files)
    out = HFLogReader(repo_id="ignored/test", hf_api=api).read()
    assert [r.turn_index for r in out] == [1]


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


# ---------------------------------------------------------------------------
# Smart-normalize: pre-v4 records carrying GAP_PHRASE read as event_type='gap'
# ---------------------------------------------------------------------------


def _record_with_answer(schema_version: str, answer: str, event_type: str = "answered") -> dict:
    return _record() | {
        "schema_version": schema_version,
        "event_type": event_type,
        "attempts": [
            {"answer": answer, "is_acceptable": True, "guardrail_feedback": ""},
        ],
    }


@pytest.mark.parametrize("schema_version", ["1", "2", "3"])
def test_read_smart_normalizes_pre_v4_record_with_gap_phrase_to_event_type_gap(
    schema_version, tmp_path
):
    """Pre-v4 records were written by the buggy producer (only answered/refused
    emitted). Where the canonical GAP_PHRASE is present in the last accepted
    answer, the read-time event_type is upgraded to 'gap' so live tabs see
    the real outcome shape without backfilling on disk.

    The rule keys on `schema_version != SCHEMA_VERSION`, not on a hard-coded
    "3" — the audit generalized the PRD's v3-only rule because GAP_PHRASE has
    been canonical across all schema versions and 8+ historical v1 records
    contain it.
    """
    from rules import GAP_PHRASE

    log_path = tmp_path / "interactions.jsonl"
    answer = f"That's a great question. {GAP_PHRASE} Happy to discuss adjacent work."
    legacy = _record_with_answer(schema_version, answer)
    _write_jsonl(log_path, [legacy])

    out = LocalReader(log_path).read()

    assert out[0].event_type == "gap", (
        f"v{schema_version} record carrying GAP_PHRASE must read as event_type='gap'"
    )
    assert out[0].schema_version == schema_version, "on-disk schema_version preserved"


def test_read_does_not_apply_deflection_markers_to_pre_v4_records(tmp_path):
    """Pre-v4 prompts didn't carry the DEFLECTION_MARKERS contract — the model
    wasn't instructed to begin redirects with the canonical phrasing. We
    therefore can't retroactively classify a pre-v4 marker-bearing answer as
    'deflected' without false positives. Smart-normalize is GAP_PHRASE-only.
    """
    from rules import DEFLECTION_MARKERS

    log_path = tmp_path / "interactions.jsonl"
    answer = f"{DEFLECTION_MARKERS[0]} about Alejandro's work."
    legacy = _record_with_answer("1", answer, event_type="answered")
    _write_jsonl(log_path, [legacy])

    out = LocalReader(log_path).read()

    assert out[0].event_type == "answered", (
        "DEFLECTION_MARKERS must not be retro-applied — pre-v4 prompts didn't enforce them"
    )


# ---------------------------------------------------------------------------
# Schema-migration layer (issue #48 / Phase 6 slice C) — reader integration
# ---------------------------------------------------------------------------


def test_read_migrates_v1_shape_record_through_local_reader(tmp_path):
    """End-to-end: a record on disk in genuine v1 shape — no
    classifier_labels, no reproducibility fields, no canary fields —
    reads back through ``LocalReader.read()`` without raising. Proves
    ``SchemaVersionHandler`` is wired into the parse path and that the
    cumulative defaults map covers the real legacy shape (the 85+ live
    records the schema bumps grew out of)."""
    log_path = tmp_path / "interactions.jsonl"
    v1 = _record() | {"schema_version": "1"}
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
    _write_jsonl(log_path, [v1])

    out = LocalReader(log_path).read()

    assert len(out) == 1, "v1 record must round-trip; the reader must not skip it"
    assert out[0].schema_version == "1", "on-disk v1 stamp preserved through migration"
    assert out[0].classifier_labels == []
    assert out[0].git_sha is None
    assert out[0].is_canary is False
    assert out[0].run_id is None


def test_read_skips_record_missing_required_field_with_warning(tmp_path, caplog):
    """A record on disk missing a required field (e.g. ``timestamp``)
    must be skipped — not crash the read — with a warning that names
    the field and the record's session_id + turn_index. This is the
    ``MissingRequiredFieldError`` path; it subclasses ``ValueError`` so
    the existing ``except (json.JSONDecodeError, ValueError)`` in
    ``_parse_jsonl_to_records`` catches it without code change."""
    import logging as _logging

    log_path = tmp_path / "interactions.jsonl"
    bad = _record(turn_index=0)
    bad.pop("timestamp")  # required at every schema version
    good = _record(timestamp="2026-05-07T12:00:00+00:00", turn_index=1)
    _write_jsonl(log_path, [bad, good])

    with caplog.at_level(_logging.WARNING, logger="log_reader"):
        out = LocalReader(log_path).read()

    assert [r.turn_index for r in out] == [1], (
        "the malformed record must be skipped, the well-formed one survives"
    )
    msg = " ".join(rec.message for rec in caplog.records)
    assert "timestamp" in msg, "warning must name the missing field"
    assert "sess-abc" in msg, "warning must name the record's session_id for triage"


def test_read_passes_v4_records_through_without_normalize(tmp_path):
    """v4 records carry the real producer-emitted event_type — the read path
    must trust them and not second-guess. Even if the answer text contains
    GAP_PHRASE (e.g. quoted in a discussion), the on-disk event_type wins."""
    from rules import GAP_PHRASE

    log_path = tmp_path / "interactions.jsonl"
    answer = f"I once said \"{GAP_PHRASE}\" to a recruiter — then explained."
    record = _record_with_answer("4", answer, event_type="answered")
    _write_jsonl(log_path, [record])

    out = LocalReader(log_path).read()

    assert out[0].event_type == "answered", "v4 records must not be smart-normalized"


# ---------------------------------------------------------------------------
# Phase 6 slice D — make_log_reader factory + HFLogReader session cache (#49)
# ---------------------------------------------------------------------------


def test_make_log_reader_returns_local_when_hf_token_absent(monkeypatch):
    """No ``HF_TOKEN`` in env → ``LocalReader``. The default for dev
    environments where the operator runs Sentinel against
    ``data/logs/interactions.jsonl``."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)

    reader = make_log_reader()

    assert isinstance(reader, LocalReader)


def test_make_log_reader_returns_hf_reader_when_token_and_repo_set(monkeypatch):
    """``HF_TOKEN`` + ``HF_DATASET_REPO`` set → ``HFLogReader`` against
    that repo. Mirrors ``make_log_writer``'s shape so a Space provisioned
    with both env vars reads and writes the same dataset."""
    monkeypatch.setenv("HF_TOKEN", "fake-read-token")
    monkeypatch.setenv("HF_DATASET_REPO", "Alejandrofupi/digital-twin-logs")

    reader = make_log_reader()

    assert isinstance(reader, HFLogReader)
    assert reader._repo_id == "Alejandrofupi/digital-twin-logs"


def test_make_log_reader_force_local_overrides_hf_env(monkeypatch):
    """``--local`` CLI flag (force_local=True) returns ``LocalReader``
    even when full HF creds are present — the operator's escape hatch
    for running Sentinel against dev logs while a prod HF env is set."""
    monkeypatch.setenv("HF_TOKEN", "fake-read-token")
    monkeypatch.setenv("HF_DATASET_REPO", "Alejandrofupi/digital-twin-logs")

    reader = make_log_reader(force_local=True)

    assert isinstance(reader, LocalReader)


def test_make_log_reader_token_set_but_repo_missing_raises(monkeypatch):
    """``HF_TOKEN`` but no ``HF_DATASET_REPO`` is a half-configured prod
    env. Raise loudly at construction rather than silently degrading
    to local — same fail-fast contract ``make_log_writer`` uses."""
    monkeypatch.setenv("HF_TOKEN", "fake-read-token")
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)

    with pytest.raises(RuntimeError, match=r"HF_DATASET_REPO"):
        make_log_reader()


def test_hf_log_reader_caches_repo_listing_within_session():
    """The first ``read()`` lists the repo once; subsequent reads re-walk
    the cache without re-listing. Sentinel opens many panels off the same
    reader — re-listing per-panel would burn an HF API call each time."""
    files = {
        "logs/2026-05-06.jsonl": [_record(timestamp="2026-05-06T10:00:00+00:00", turn_index=1)],
        "logs/2026-05-07.jsonl": [_record(timestamp="2026-05-07T10:00:00+00:00", turn_index=2)],
    }
    api = _hf_api_for_reader(files)
    reader = HFLogReader(repo_id="ignored/test", hf_api=api)

    reader.read()
    reader.read()
    reader.read()

    assert api.list_repo_files.call_count == 1, (
        "list_repo_files must be called once per session, not per-read"
    )


def test_hf_log_reader_caches_per_file_downloads_within_session():
    """Each per-day file is downloaded + parsed once per session.
    Reading 7d then 30d must NOT re-download the days that overlap."""
    files = {
        "logs/2026-05-06.jsonl": [_record(timestamp="2026-05-06T10:00:00+00:00", turn_index=1)],
        "logs/2026-05-07.jsonl": [_record(timestamp="2026-05-07T10:00:00+00:00", turn_index=2)],
    }
    api = _hf_api_for_reader(files)
    reader = HFLogReader(repo_id="ignored/test", hf_api=api)

    reader.read()
    downloads_after_first = api.hf_hub_download.call_count

    reader.read()
    downloads_after_second = api.hf_hub_download.call_count

    assert downloads_after_first == 2, "first read downloads each per-day file once"
    assert downloads_after_second == 2, (
        "second read must hit the cache; no extra downloads"
    )


def test_hf_log_reader_invalidate_cache_re_fetches():
    """``invalidate_cache()`` is the Refresh-button hook — after a call,
    the next ``read()`` re-lists the repo and re-downloads the files,
    so records appended since the session opened show up."""
    files = {
        "logs/2026-05-07.jsonl": [_record(timestamp="2026-05-07T10:00:00+00:00", turn_index=1)],
    }
    api = _hf_api_for_reader(files)
    reader = HFLogReader(repo_id="ignored/test", hf_api=api)

    reader.read()
    reader.invalidate_cache()
    reader.read()

    assert api.list_repo_files.call_count == 2, "invalidate forces a re-list"
    assert api.hf_hub_download.call_count == 2, "invalidate forces a re-download"

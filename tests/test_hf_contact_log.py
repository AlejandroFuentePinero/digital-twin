"""Phase 6 / slice E (#50) — HF-Dataset-backed contact log writer + reader.

Mock at the ``huggingface_hub`` boundary, same pattern as
``test_hf_log_writer.py`` / ``test_log_reader.py``. The shared LogBuffer
+ flush thread + crash recovery + SIGTERM-drain machinery is already
covered by the slice-A/B suites against ``HFLogWriter``; these tests
cover the slice-E-specific differentiators: contact path prefix,
contact buffer file, dedup-by-(session_id, timestamp), and the
``make_contact_*`` factories.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _contact_record(session_id: str = "sess-1", timestamp: str = "2026-05-07T12:00:00+00:00") -> dict:
    return {
        "schema_version": "1",
        "timestamp": timestamp,
        "session_id": session_id,
        "turn_index": 3,
        "email": f"{session_id}@example.com",
        "name": None,
        "note": None,
    }


def _hf_api_for_writer() -> MagicMock:
    api = MagicMock()
    api.upload_file = MagicMock(return_value=None)
    api.hf_hub_download = MagicMock(side_effect=FileNotFoundError())
    return api


def _hf_api_for_reader(files_by_path: dict[str, list[dict]]) -> MagicMock:
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


# ---------------------------------------------------------------------------
# HFContactWriter — path prefix, buffer file, no state-file (overrides only)
# ---------------------------------------------------------------------------


def test_hf_contact_writer_uploads_to_contacts_path_prefix(tmp_path):
    """Records group by UTC date and commit to ``contacts/YYYY-MM-DD.jsonl`` —
    distinct from the interaction-log writer's ``logs/...`` so the two
    log streams are independently queryable in the dataset."""
    from hf_contact_log import HFContactWriter

    api = _hf_api_for_writer()
    writer = HFContactWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_contact_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_contact_record("a", "2026-05-06T23:30:00+00:00"))
    writer.append(_contact_record("b", "2026-05-07T00:30:00+00:00"))

    writer.flush()

    paths = sorted(call.kwargs["path_in_repo"] for call in api.upload_file.call_args_list)
    assert paths == ["contacts/2026-05-06.jsonl", "contacts/2026-05-07.jsonl"]


def test_hf_contact_writer_does_not_emit_writer_state_file(tmp_path):
    """Slice E intentionally skips slice D's ``hf_writer_state.json``
    upload — contact volume is too low for the staleness signal to
    be meaningful, and the spec doesn't ask for it. So the only
    ``upload_file`` calls during a flush should target ``contacts/``."""
    from hf_contact_log import HFContactWriter

    api = _hf_api_for_writer()
    writer = HFContactWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_contact_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_contact_record())
    writer.flush()

    state_uploads = [
        call
        for call in api.upload_file.call_args_list
        if call.kwargs.get("path_in_repo") == "hf_writer_state.json"
    ]
    assert state_uploads == [], (
        "HFContactWriter must not emit hf_writer_state.json — that's "
        "slice-D's interaction-log diagnostic and contact volume is "
        "too low to make staleness a useful signal"
    )


def test_hf_contact_writer_uses_dedicated_buffer_file_by_default(tmp_path, monkeypatch):
    """The contact-log buffer must live at a different path from the
    interaction-log buffer so a flush of one doesn't truncate the other."""
    from hf_contact_log import DEFAULT_CONTACT_BUFFER_PATH
    from hf_log_writer import DEFAULT_BUFFER_PATH

    assert DEFAULT_CONTACT_BUFFER_PATH != DEFAULT_BUFFER_PATH, (
        "contact buffer path must differ from interaction-log buffer"
    )
    assert DEFAULT_CONTACT_BUFFER_PATH.parent == DEFAULT_BUFFER_PATH.parent, (
        "both buffer files live under data/logs/ (gitignored together)"
    )


def test_hf_contact_writer_inherits_buffer_and_failure_semantics(tmp_path, caplog):
    """Inheriting from ``HFLogWriter`` means a flush failure must
    preserve the buffer for retry, same as the interaction-log writer's
    contract — the per-turn pipeline never sees a flush failure."""
    import logging

    from hf_contact_log import HFContactWriter

    api = _hf_api_for_writer()
    api.upload_file.side_effect = RuntimeError("hf is down")
    writer = HFContactWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_contact_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_contact_record("a"))
    writer.append(_contact_record("b"))

    with caplog.at_level(logging.ERROR, logger="hf_log_writer"):
        writer.flush()  # must not raise

    assert writer.buffer_size() == 2, "records preserved for retry"


# ---------------------------------------------------------------------------
# HFContactReader — path regex, dedup key, caching
# ---------------------------------------------------------------------------


def test_hf_contact_reader_lists_only_contacts_path(tmp_path):
    """``list_repo_files`` returns everything in the repo (READMEs,
    interaction-log files, etc.); the reader must filter to
    ``contacts/*.jsonl``. This is the symmetry of ``HFLogReader``
    skipping non-``logs/`` paths."""
    from hf_contact_log import HFContactReader

    files = {
        "README.md": [],
        "logs/2026-05-07.jsonl": [],  # interaction-log file, must be skipped
        "contacts/2026-05-07.jsonl": [_contact_record("a")],
    }
    api = _hf_api_for_reader(files)

    out = HFContactReader(repo_id="ignored/test", hf_api=api).read_all()

    assert [r["session_id"] for r in out] == ["a"]


def test_hf_contact_reader_dedupes_by_session_and_timestamp(tmp_path):
    """A flush retry can ship the same contact record twice. The
    dedup key is ``(session_id, timestamp)``; same key collapses,
    different key (e.g. same visitor submitting twice) is preserved."""
    from hf_contact_log import HFContactReader

    duplicate = _contact_record("a", "2026-05-07T12:00:00+00:00")
    different_timestamp = _contact_record("a", "2026-05-07T13:00:00+00:00")
    files = {
        "contacts/2026-05-07.jsonl": [duplicate, duplicate, different_timestamp],
    }
    api = _hf_api_for_reader(files)

    out = HFContactReader(repo_id="ignored/test", hf_api=api).read_all()

    timestamps = sorted(r["timestamp"] for r in out)
    assert timestamps == [
        "2026-05-07T12:00:00+00:00",
        "2026-05-07T13:00:00+00:00",
    ]


def test_hf_contact_reader_returns_empty_when_no_contact_files_in_repo(tmp_path):
    """Cold dataset (writer hasn't completed a flush yet) → empty list,
    not an error — same shape as the local ``ContactReader`` returns
    when the file is missing."""
    from hf_contact_log import HFContactReader

    api = _hf_api_for_reader({"README.md": []})
    out = HFContactReader(repo_id="ignored/test", hf_api=api).read_all()
    assert out == []


def test_hf_contact_reader_caches_listing_and_downloads_per_session(tmp_path):
    """Sentinel reads contacts once on launch via
    ``read_provided_session_ids``; if the underlying reader didn't
    cache, opening multiple panels would burn HF API calls. Mirrors
    the per-session caching contract of ``HFLogReader``."""
    from hf_contact_log import HFContactReader

    files = {
        "contacts/2026-05-07.jsonl": [_contact_record("a")],
    }
    api = _hf_api_for_reader(files)
    reader = HFContactReader(repo_id="ignored/test", hf_api=api)

    reader.read_all()
    reader.read_all()
    reader.read_all()

    assert api.list_repo_files.call_count == 1
    assert api.hf_hub_download.call_count == 1


def test_hf_contact_reader_skips_malformed_line_with_warning(tmp_path, caplog):
    """A bad JSON line must not take down the read — log a warning
    and surface the surrounding well-formed records, same resilience
    contract the interaction-log reader uses."""
    import logging

    from hf_contact_log import HFContactReader

    # Inject a malformed line via a custom api that returns a path
    # to a JSONL file containing invalid JSON in the middle.
    valid = _contact_record("a")
    bad_file = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    bad_file.write(json.dumps(valid) + "\n")
    bad_file.write("{not valid json\n")
    bad_file.write(json.dumps(_contact_record("c")) + "\n")
    bad_file.close()

    api = MagicMock()
    api.list_repo_files = MagicMock(return_value=["contacts/2026-05-07.jsonl"])
    api.hf_hub_download = MagicMock(return_value=bad_file.name)

    with caplog.at_level(logging.WARNING, logger="hf_contact_log"):
        out = HFContactReader(repo_id="ignored/test", hf_api=api).read_all()

    assert sorted(r["session_id"] for r in out) == ["a", "c"]


# ---------------------------------------------------------------------------
# make_contact_writer / make_contact_reader factories (#50)
# ---------------------------------------------------------------------------


def test_make_contact_writer_default_returns_local_writer(monkeypatch, tmp_path):
    """Default (no ``DIGITAL_TWIN_LOG_BACKEND`` env var) → the local
    JSONL ``ContactWriter``. Mirrors ``make_log_writer``'s default."""
    from contact_log import ContactWriter, make_contact_writer

    monkeypatch.delenv("DIGITAL_TWIN_LOG_BACKEND", raising=False)
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    writer = make_contact_writer(local_path=tmp_path / "contacts.jsonl")
    assert isinstance(writer, ContactWriter)


def test_make_contact_writer_hf_returns_hf_writer_with_thread_started(monkeypatch, tmp_path):
    """``DIGITAL_TWIN_LOG_BACKEND=hf`` + ``HF_DATASET_REPO`` →
    ``HFContactWriter``, started + atexit-registered. ``auto_start=False``
    keeps the test thread-free; the env-driven factory branch is what's
    under test, not the threading."""
    from contact_log import make_contact_writer
    from hf_contact_log import HFContactWriter

    monkeypatch.setenv("DIGITAL_TWIN_LOG_BACKEND", "hf")
    monkeypatch.setenv("HF_DATASET_REPO", "Alejandrofupi/digital-twin-logs-test")
    monkeypatch.setenv("HF_TOKEN", "fake-token")

    writer = make_contact_writer(
        buffer_path=tmp_path / ".hf_contact_buffer.jsonl",
        auto_start=False,
    )

    assert isinstance(writer, HFContactWriter)
    assert writer._repo_id == "Alejandrofupi/digital-twin-logs-test"


def test_make_contact_writer_hf_without_repo_raises(monkeypatch):
    """``DIGITAL_TWIN_LOG_BACKEND=hf`` but no ``HF_DATASET_REPO`` is a
    half-configured prod env — fail loudly, same contract as
    ``make_log_writer``."""
    from contact_log import make_contact_writer

    monkeypatch.setenv("DIGITAL_TWIN_LOG_BACKEND", "hf")
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)

    with pytest.raises(RuntimeError, match=r"HF_DATASET_REPO|backend"):
        make_contact_writer()


def test_make_contact_reader_returns_local_when_hf_token_absent(monkeypatch):
    """No ``HF_TOKEN`` → ``ContactReader`` (local). Mirrors
    ``make_log_reader``'s default — Sentinel running locally never
    accidentally reaches for HF creds."""
    from contact_log import ContactReader, make_contact_reader

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)

    reader = make_contact_reader()
    assert isinstance(reader, ContactReader)


def test_make_contact_reader_returns_hf_reader_when_token_and_repo_set(monkeypatch):
    """``HF_TOKEN`` + ``HF_DATASET_REPO`` → ``HFContactReader`` —
    Sentinel sees production contacts without per-call configuration."""
    from contact_log import make_contact_reader
    from hf_contact_log import HFContactReader

    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("HF_DATASET_REPO", "Alejandrofupi/digital-twin-logs")

    reader = make_contact_reader()
    assert isinstance(reader, HFContactReader)
    assert reader._repo_id == "Alejandrofupi/digital-twin-logs"


def test_make_contact_reader_force_local_overrides_hf_env(monkeypatch):
    """The operator's ``--local`` escape hatch (Sentinel's CLI flag
    propagates here) must force ``ContactReader`` even with full HF
    creds in env."""
    from contact_log import ContactReader, make_contact_reader

    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("HF_DATASET_REPO", "Alejandrofupi/digital-twin-logs")

    reader = make_contact_reader(force_local=True)
    assert isinstance(reader, ContactReader)


def test_make_contact_reader_token_set_but_repo_missing_raises(monkeypatch):
    """``HF_TOKEN`` set + ``HF_DATASET_REPO`` missing is a half-
    configured prod env — raise loudly, same contract as
    ``make_log_reader``."""
    from contact_log import make_contact_reader

    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)

    with pytest.raises(RuntimeError, match=r"HF_DATASET_REPO"):
        make_contact_reader()


def test_read_provided_session_ids_uses_factory_default(monkeypatch, tmp_path):
    """Called with no args, ``read_provided_session_ids`` falls
    through to ``make_contact_reader()`` so Sentinel becomes
    HF-aware automatically — no Sentinel-side changes for slice E."""
    from contact_log import read_provided_session_ids

    fake_reader = MagicMock()
    fake_reader.read_all = MagicMock(return_value=[
        {"session_id": "a"}, {"session_id": "b"},
    ])
    monkeypatch.setattr(
        "contact_log.make_contact_reader",
        lambda: fake_reader,
    )

    out = read_provided_session_ids()

    assert out == {"a", "b"}
    fake_reader.read_all.assert_called_once()


def test_read_provided_session_ids_explicit_path_still_works(tmp_path):
    """Back-compat: tests pinning the local file path keep working
    (existing test_contact_log.py tests rely on this)."""
    from contact_log import ContactWriter, read_provided_session_ids

    log = tmp_path / "contacts.jsonl"
    ContactWriter(log).append({
        "timestamp": "2026-05-07T12:00:00+00:00",
        "session_id": "a",
        "turn_index": 3,
        "email": "a@example.com",
    })

    out = read_provided_session_ids(log)

    assert out == {"a"}


# ---------------------------------------------------------------------------
# install_sigterm_handler now accepts multiple writers (#50)
# ---------------------------------------------------------------------------


def test_install_sigterm_handler_drains_multiple_writers(monkeypatch):
    """Slice E extends the slice-B handler so one signal drains both
    the interaction-log writer and the contact-log writer."""
    import signal

    from hf_log_writer import install_sigterm_handler

    captured = []
    monkeypatch.setattr(signal, "signal", lambda signum, handler: captured.append((signum, handler)))

    log_writer = MagicMock(spec=["stop"])
    contact_writer = MagicMock(spec=["stop"])

    installed = install_sigterm_handler(log_writer, contact_writer)
    assert installed is True
    assert captured and captured[0][0] == signal.SIGTERM

    # Invoke the registered handler — must call stop on BOTH writers.
    handler = captured[0][1]
    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGTERM, None)
    assert exc_info.value.code == 0

    log_writer.stop.assert_called_once()
    contact_writer.stop.assert_called_once()


def test_install_sigterm_handler_one_writer_stop_failure_does_not_block_others(monkeypatch):
    """A failure in one writer's ``stop`` must not stop the other
    writer from being drained — the handler is best-effort, all-the-way
    through, before ``sys.exit``."""
    import signal

    from hf_log_writer import install_sigterm_handler

    captured = []
    monkeypatch.setattr(signal, "signal", lambda signum, handler: captured.append((signum, handler)))

    log_writer = MagicMock(spec=["stop"])
    log_writer.stop.side_effect = RuntimeError("flush failed")
    contact_writer = MagicMock(spec=["stop"])

    install_sigterm_handler(log_writer, contact_writer)
    handler = captured[0][1]
    with pytest.raises(SystemExit):
        handler(signal.SIGTERM, None)

    log_writer.stop.assert_called_once()
    contact_writer.stop.assert_called_once(), (
        "second writer must still be drained even if first writer's stop raised"
    )


def test_install_sigterm_handler_no_writer_with_stop_returns_false(monkeypatch):
    """All writers without a ``stop`` (e.g. both backends are local) →
    no handler installed, return False. Existing slice-B contract."""
    import signal

    from hf_log_writer import install_sigterm_handler

    monkeypatch.setattr(signal, "signal", lambda *args: pytest.fail("must not register"))

    local_log = MagicMock(spec=[])  # no stop method
    local_contact = MagicMock(spec=[])

    installed = install_sigterm_handler(local_log, local_contact)
    assert installed is False

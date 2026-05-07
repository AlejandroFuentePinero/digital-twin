"""Phase 6 / slice A — buffered HF writer + buffer primitive.

The buffer is the data-side piece (issue #46): pure-data accumulator with a
disk-backed JSONL fallback at ``data/logs/.hf_buffer.jsonl`` so an
unflushed buffer survives a Space restart. The HFLogWriter wraps it, owns
the flush policy, and is the only thing that talks to ``huggingface_hub``.
Reader-side dedup tests live in ``tests/test_log_reader.py``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _record(turn_index: int = 0, session_id: str = "sess-1") -> dict:
    return {
        "schema_version": "4",
        "timestamp": "2026-05-07T12:00:00+00:00",
        "session_id": session_id,
        "turn_index": turn_index,
        "question": "Tell me about your background.",
        "event_type": "answered",
        "branch": "GENERIC",
        "classification_confidence": 1.0,
        "attempts": [{"answer": "Hi.", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 1, "retrieval": 1, "generation": 1, "guardrail": 1, "total": 4},
        "knew_answer": True,
        "contact_offered": False,
        "contact_provided": False,
    }


# ---------------------------------------------------------------------------
# LogBuffer (TDD)
# ---------------------------------------------------------------------------


def test_append_grows_size_and_flush_returns_records_and_clears(tmp_path):
    from hf_log_writer import LogBuffer

    buf = LogBuffer(tmp_path / ".hf_buffer.jsonl")
    assert buf.size() == 0

    buf.append(_record(0))
    buf.append(_record(1))
    assert buf.size() == 2

    drained = buf.flush()
    assert [r["turn_index"] for r in drained] == [0, 1]
    assert buf.size() == 0


def test_append_persists_to_disk_and_survives_new_instance(tmp_path):
    """The disk-backed fallback at ``.hf_buffer.jsonl`` exists exactly so an
    unflushed buffer survives a process restart."""
    from hf_log_writer import LogBuffer

    path = tmp_path / ".hf_buffer.jsonl"
    buf1 = LogBuffer(path)
    buf1.append(_record(0))
    buf1.append(_record(1))

    # Simulate a restart — new instance, same path.
    buf2 = LogBuffer(path)
    assert buf2.size() == 2
    drained = buf2.flush()
    assert [r["turn_index"] for r in drained] == [0, 1]


def test_flush_truncates_the_disk_file(tmp_path):
    from hf_log_writer import LogBuffer

    path = tmp_path / ".hf_buffer.jsonl"
    buf = LogBuffer(path)
    buf.append(_record(0))
    assert path.exists() and path.read_text().strip() != ""

    buf.flush()
    # File may exist as an empty file or be removed — either is fine. What
    # matters: a fresh instance loads zero records.
    assert LogBuffer(path).size() == 0


def test_is_full_thresholds_on_size(tmp_path):
    from hf_log_writer import LogBuffer

    buf = LogBuffer(tmp_path / ".hf_buffer.jsonl")
    assert not buf.is_full(1)
    buf.append(_record(0))
    assert buf.is_full(1)
    assert not buf.is_full(2)


def test_time_since_last_flush_grows_then_resets_on_flush(tmp_path):
    from hf_log_writer import LogBuffer

    buf = LogBuffer(tmp_path / ".hf_buffer.jsonl")
    t0 = buf.time_since_last_flush()
    time.sleep(0.05)
    t1 = buf.time_since_last_flush()
    assert t1 > t0

    buf.append(_record(0))
    buf.flush()
    t2 = buf.time_since_last_flush()
    assert t2 < t1, "flush must reset the elapsed clock"


def test_append_appends_to_existing_jsonl_without_overwriting(tmp_path):
    """Two appends must produce two lines on disk, not one."""
    from hf_log_writer import LogBuffer

    path = tmp_path / ".hf_buffer.jsonl"
    buf = LogBuffer(path)
    buf.append(_record(0))
    buf.append(_record(1))

    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert [json.loads(ln)["turn_index"] for ln in lines] == [0, 1]


# ---------------------------------------------------------------------------
# HFLogWriter — non-blocking append, size + interval flush, error handling
# ---------------------------------------------------------------------------


def _hf_api_mock() -> MagicMock:
    """A MagicMock standing in for ``huggingface_hub.HfApi``. The writer's
    only network surface is this object — every flush test mocks it here
    rather than reaching for ``requests`` or HTTP."""
    api = MagicMock()
    api.upload_file = MagicMock(return_value=None)
    api.hf_hub_download = MagicMock(side_effect=FileNotFoundError())
    return api


def _data_upload_count(api: MagicMock) -> int:
    """Number of ``upload_file`` calls that targeted a per-day ``logs/``
    file. Excludes ``hf_writer_state.json`` (which is uploaded by every
    flush attempt as a diagnostic alongside the data — #49). Tests that
    assert "the flush fired" should compare against this rather than
    ``api.upload_file.call_count`` so a state-file upload doesn't shift
    the count."""
    return sum(
        1
        for call in api.upload_file.call_args_list
        if str(call.kwargs.get("path_in_repo", "")).startswith("logs/")
    )


def test_append_is_non_blocking_no_hf_call_on_hot_path(tmp_path):
    """The hot path (one ``append``) must never reach huggingface_hub —
    the whole point of the buffer is to keep the per-turn pipeline off
    the network."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0))

    api.upload_file.assert_not_called()
    api.hf_hub_download.assert_not_called()


def test_size_trigger_flushes_when_buffer_hits_threshold(tmp_path):
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=3,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0))
    writer.append(_record(1))
    assert _data_upload_count(api) == 0
    writer.append(_record(2))
    # Synchronous flush (the background task delegates to the same path).
    writer.maybe_flush()
    assert _data_upload_count(api) == 1


def test_interval_trigger_flushes_when_clock_advances_past_interval(tmp_path):
    """Time-driven flush is mocked at the clock boundary (``time.monotonic``)
    so the test doesn't sleep."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    fake_now = [1000.0]

    def fake_clock() -> float:
        return fake_now[0]

    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
        clock=fake_clock,
    )
    writer.append(_record(0))

    # Below interval — no flush yet.
    fake_now[0] = 1000.0 + 599.0
    writer.maybe_flush()
    assert _data_upload_count(api) == 0

    # Past interval — flush fires.
    fake_now[0] = 1000.0 + 600.5
    writer.maybe_flush()
    assert _data_upload_count(api) == 1


def test_flush_groups_records_by_utc_date_one_commit_per_day(tmp_path):
    """Records timestamped on different UTC days commit to separate files
    (``logs/YYYY-MM-DD.jsonl``)."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0) | {"timestamp": "2026-05-06T23:30:00+00:00"})
    writer.append(_record(1) | {"timestamp": "2026-05-07T00:30:00+00:00"})
    writer.append(_record(2) | {"timestamp": "2026-05-07T01:00:00+00:00"})

    writer.flush()

    paths_in_repo = sorted(
        call.kwargs.get("path_in_repo")
        for call in api.upload_file.call_args_list
        if str(call.kwargs.get("path_in_repo", "")).startswith("logs/")
    )
    assert paths_in_repo == ["logs/2026-05-06.jsonl", "logs/2026-05-07.jsonl"]


def test_flush_failure_logs_and_preserves_buffer(tmp_path, caplog):
    """If the HF upload raises, the buffer must NOT be cleared — so a
    later retry can still ship those records — and the error is logged
    rather than propagated up the per-turn pipeline."""
    import logging

    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    api.upload_file.side_effect = RuntimeError("hf is down")

    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=2,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0))
    writer.append(_record(1))

    with caplog.at_level(logging.ERROR, logger="hf_log_writer"):
        writer.flush()  # must not raise

    assert writer.buffer_size() == 2, "records must remain buffered for next retry"
    assert any("flush" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Phase 6 slice D — hf_writer_state.json (#49)
# ---------------------------------------------------------------------------


def _state_uploads(api: MagicMock) -> list[dict]:
    """Decode every ``upload_file`` call that targeted the state filename
    so the tests can inspect the JSON payload without re-parsing the
    bytes by hand."""
    out: list[dict] = []
    for call in api.upload_file.call_args_list:
        if call.kwargs.get("path_in_repo") != "hf_writer_state.json":
            continue
        body = call.kwargs.get("path_or_fileobj")
        if isinstance(body, bytes):
            out.append(json.loads(body.decode("utf-8")))
    return out


def test_flush_success_uploads_writer_state_with_zero_buffer_no_error(tmp_path):
    """After a successful flush, ``hf_writer_state.json`` is committed
    to the dataset with ``last_flush_time`` populated, ``buffer_size=0``
    (the buffer was just drained), and ``last_error=None``. Sentinel's
    Log writer health panel reads exactly this file (#49)."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0))
    writer.append(_record(1))

    writer.flush()

    states = _state_uploads(api)
    assert len(states) == 1, "exactly one state-file upload per flush"
    state = states[0]
    assert state["buffer_size"] == 0, "post-success the buffer is drained"
    assert state["last_error"] is None
    assert state["last_flush_time"] is not None


def test_flush_failure_uploads_writer_state_with_buffer_size_and_last_error(
    tmp_path, caplog
):
    """A flush that fails the data upload still attempts to commit a state
    file — that's the whole point of the panel: Sentinel must see "HF is
    silently failing to flush". The state carries ``buffer_size`` (records
    still queued) and ``last_error`` (a short string a human can read)."""
    import logging

    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()

    def _fail_data_only(*args, **kwargs):
        # The state file is allowed to upload; only the per-day data file fails.
        if kwargs.get("path_in_repo", "").startswith("logs/"):
            raise RuntimeError("hf is down")
        return None

    api.upload_file.side_effect = _fail_data_only

    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0))
    writer.append(_record(1))

    with caplog.at_level(logging.ERROR, logger="hf_log_writer"):
        writer.flush()  # must not raise

    assert writer.buffer_size() == 2, "buffer preserved for retry"
    states = _state_uploads(api)
    assert len(states) == 1, "state file must still be committed on failure"
    state = states[0]
    assert state["buffer_size"] == 2, "state surfaces the un-shipped record count"
    assert state["last_error"] is not None
    assert "hf is down" in state["last_error"]


def test_state_upload_failure_does_not_break_flush(tmp_path):
    """If the state-file upload itself raises, the data flush must still
    have committed and the buffer must still be drained. The state file
    is diagnostic — it must never gate the durability path."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()

    def _fail_state_only(*args, **kwargs):
        if kwargs.get("path_in_repo") == "hf_writer_state.json":
            raise RuntimeError("state upload broke")
        return None

    api.upload_file.side_effect = _fail_state_only

    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0))
    writer.flush()  # must not raise

    assert writer.buffer_size() == 0, "data flush succeeded; buffer drained"


def test_read_writer_state_returns_none_when_state_file_missing():
    """Sentinel asks for the state file before any flush has happened
    (cold dataset). The reader returns ``None`` so the panel can render
    a 'no flushes yet' placeholder rather than crashing."""
    from huggingface_hub.utils import EntryNotFoundError
    from hf_log_writer import read_writer_state

    api = MagicMock()
    api.hf_hub_download = MagicMock(side_effect=EntryNotFoundError("missing"))

    state = read_writer_state(api, repo_id="ignored/test")

    assert state is None


def test_read_writer_state_returns_parsed_dict_when_present(tmp_path):
    """When ``hf_writer_state.json`` is present, the reader returns the
    parsed dict so Sentinel can index ``last_flush_time``/``buffer_size``/
    ``last_error`` directly."""
    from hf_log_writer import read_writer_state

    state_file = tmp_path / "hf_writer_state.json"
    state_file.write_text(json.dumps({
        "last_flush_time": "2026-05-07T12:00:00+00:00",
        "buffer_size": 0,
        "last_error": None,
    }))
    api = MagicMock()
    api.hf_hub_download = MagicMock(return_value=str(state_file))

    state = read_writer_state(api, repo_id="ignored/test")

    assert state is not None
    assert state["last_flush_time"] == "2026-05-07T12:00:00+00:00"
    assert state["buffer_size"] == 0
    assert state["last_error"] is None


def test_flush_with_empty_buffer_is_a_noop(tmp_path):
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.flush()
    api.upload_file.assert_not_called()


def test_background_thread_flushes_on_size_trigger(tmp_path):
    """The background poller calls ``maybe_flush`` on its own — when the
    buffer fills past ``flush_batch_size``, the next poll fires the
    flush without any caller intervention."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=2,
        flush_interval_seconds=600,
        hf_api=api,
        poll_interval_seconds=0.01,
    )
    writer.start()
    try:
        writer.append(_record(0))
        writer.append(_record(1))
        # Give the poller up to 1s — generous on a slow CI box but
        # asymptotic to the 10ms poll interval.
        deadline = time.monotonic() + 1.0
        while _data_upload_count(api) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        writer.stop()
    assert _data_upload_count(api) >= 1, "background poll must fire flush"


def test_background_thread_flushes_on_time_trigger_with_mocked_clock(tmp_path):
    """The interval trigger uses an injected clock so the test can jump
    past ``FLUSH_INTERVAL_SECONDS`` without sleeping for real."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    fake_now = [1000.0]

    def fake_clock() -> float:
        return fake_now[0]

    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
        clock=fake_clock,
        poll_interval_seconds=0.01,
    )
    writer.append(_record(0))
    writer.start()
    try:
        # Bump the mocked clock past the interval — the next poll should fire.
        fake_now[0] = 1000.0 + 1000.0
        deadline = time.monotonic() + 1.0
        while _data_upload_count(api) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        writer.stop()
    assert _data_upload_count(api) >= 1


def test_stop_flushes_remaining_buffer_on_clean_shutdown(tmp_path):
    """Clean shutdown is best-effort exactly-once: ``stop`` joins the
    poller, then issues one final flush so any straggler records ship
    before the process exits."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
        poll_interval_seconds=0.01,
    )
    writer.start()
    writer.append(_record(0))
    writer.stop()
    assert _data_upload_count(api) == 1
    assert writer.buffer_size() == 0


def test_flush_appends_to_existing_per_day_file_rather_than_overwriting(tmp_path):
    """When today's file already has older records on the dataset, a flush
    fetches → concatenates → uploads — so a same-day re-flush never wipes
    earlier flushes."""
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    # Pretend the dataset already has one record for 2026-05-07.
    existing_path = tmp_path / "_existing.jsonl"
    existing_path.write_text(json.dumps(_record(99)) + "\n")
    api.hf_hub_download = MagicMock(return_value=str(existing_path))

    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=10,
        flush_interval_seconds=600,
        hf_api=api,
    )
    writer.append(_record(0) | {"timestamp": "2026-05-07T01:00:00+00:00"})
    writer.flush()

    data_calls = [
        call
        for call in api.upload_file.call_args_list
        if str(call.kwargs.get("path_in_repo", "")).startswith("logs/")
    ]
    assert len(data_calls) == 1
    body = data_calls[0].kwargs["path_or_fileobj"]
    if isinstance(body, (bytes, bytearray)):
        text = body.decode("utf-8")
    else:
        text = Path(body).read_text() if isinstance(body, (str, Path)) else body.read().decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    parsed = [json.loads(ln) for ln in lines]
    assert sorted(r["turn_index"] for r in parsed) == [0, 99]


# ---------------------------------------------------------------------------
# Slice B (#47) — crash recovery: immediate flush on startup
# ---------------------------------------------------------------------------


def test_init_flushes_immediately_when_disk_buffer_is_non_empty(tmp_path):
    """Slice B crash-recovery contract: a buffer file left behind by a
    previous (crashed or SIGTERM'd) process must ship as soon as a new
    ``HFLogWriter`` is constructed — not on the next poll tick or
    size/time trigger."""
    from hf_log_writer import HFLogWriter

    buffer_path = tmp_path / ".hf_buffer.jsonl"
    buffer_path.parent.mkdir(parents=True, exist_ok=True)
    with buffer_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_record(0)) + "\n")
        f.write(json.dumps(_record(1)) + "\n")

    api = _hf_api_mock()
    writer = HFLogWriter(
        repo_id="ignored/test",
        buffer_path=buffer_path,
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
    )

    assert _data_upload_count(api) == 1
    assert writer.buffer_size() == 0


def test_init_does_not_flush_when_disk_buffer_is_missing(tmp_path):
    from hf_log_writer import HFLogWriter

    api = _hf_api_mock()
    HFLogWriter(
        repo_id="ignored/test",
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
    )
    api.upload_file.assert_not_called()


def test_init_does_not_flush_when_disk_buffer_is_empty(tmp_path):
    """An empty (zero-byte or whitespace-only) buffer file is the
    post-clean-flush state and must not trigger a network call."""
    from hf_log_writer import HFLogWriter

    buffer_path = tmp_path / ".hf_buffer.jsonl"
    buffer_path.parent.mkdir(parents=True, exist_ok=True)
    buffer_path.write_text("")

    api = _hf_api_mock()
    HFLogWriter(
        repo_id="ignored/test",
        buffer_path=buffer_path,
        flush_batch_size=50,
        flush_interval_seconds=600,
        hf_api=api,
    )
    api.upload_file.assert_not_called()


# ---------------------------------------------------------------------------
# Slice B (#47) — SIGTERM handler
# ---------------------------------------------------------------------------


def test_install_sigterm_handler_registers_handler_that_calls_stop(monkeypatch):
    """The SIGTERM path is what HF Spaces uses for container shutdown.
    The handler must final-flush via ``writer.stop`` so records in the
    buffer ship before the process dies. The handler itself terminates
    the process via ``sys.exit`` — tests intercept both to assert the
    full chain without actually killing the test runner."""
    import signal as _signal

    from hf_log_writer import install_sigterm_handler

    writer = MagicMock()
    writer.stop = MagicMock()

    installed: dict = {}

    def fake_signal(signum, handler):
        installed["signum"] = signum
        installed["handler"] = handler

    monkeypatch.setattr(_signal, "signal", fake_signal)

    assert install_sigterm_handler(writer) is True
    assert installed["signum"] == _signal.SIGTERM

    # Invoke the handler the same way the kernel would. It calls
    # sys.exit(0); intercept that so the test doesn't tear itself down.
    with pytest.raises(SystemExit) as excinfo:
        installed["handler"](_signal.SIGTERM, None)
    assert excinfo.value.code == 0
    writer.stop.assert_called_once()


def test_install_sigterm_handler_is_noop_for_writer_without_stop(monkeypatch):
    """The local-backend ``LogWriter`` has no ``stop`` method. Installing
    the handler must be a no-op so dev workflows aren't affected by a
    SIGTERM that has nothing to flush."""
    import signal as _signal

    from hf_log_writer import install_sigterm_handler

    class LocalLikeWriter:
        def append(self, _record):
            pass

    called = {"count": 0}

    def fake_signal(_signum, _handler):
        called["count"] += 1

    monkeypatch.setattr(_signal, "signal", fake_signal)

    assert install_sigterm_handler(LocalLikeWriter()) is False
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Opt-in real-network integration (gated on HF_INTEGRATION_TEST=1)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("HF_INTEGRATION_TEST") != "1",
    reason="HF integration test is opt-in (set HF_INTEGRATION_TEST=1).",
)
def test_real_round_trip_to_hf_dataset_and_back(tmp_path):
    """Writes a small batch through ``HFLogWriter`` to the configured
    test repo, then reads it back through ``HFLogReader``. This is the
    only test that touches the real network — all other coverage mocks
    at the ``HfApi`` boundary."""
    import uuid

    from dotenv import load_dotenv

    from hf_log_writer import HFLogWriter
    from log_reader import HFLogReader

    load_dotenv(override=True)
    repo_id = os.environ.get("HF_DATASET_REPO", "Alejandrofupi/digital-twin-logs")
    token = os.environ.get("HF_TOKEN")
    assert token, "HF_TOKEN must be set when HF_INTEGRATION_TEST=1"

    run_marker = uuid.uuid4().hex[:8]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    today_record = (
        _record(0)
        | {
            "session_id": f"itest-{run_marker}",
            "timestamp": today,
        }
    )

    writer = HFLogWriter(
        repo_id=repo_id,
        buffer_path=tmp_path / ".hf_buffer.jsonl",
        flush_batch_size=1,
        flush_interval_seconds=600,
        token=token,
    )
    writer.append(today_record)
    writer.flush()
    assert writer.buffer_size() == 0, "successful flush must clear the buffer"

    out = HFLogReader(repo_id=repo_id, token=token).read(days=2)
    matched = [r for r in out if r.session_id == f"itest-{run_marker}"]
    assert len(matched) == 1, f"expected our test record back; got {len(matched)} matches"

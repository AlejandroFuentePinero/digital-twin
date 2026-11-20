"""Sentinel tests. The page model (``build_page``) is the seam: every figure
the page shows is plain data there, so the tests read it directly. Readers
and the Hugging Face hub are faked at the process boundary; no LLM calls.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard_model import METRIC_GETTERS
from interaction_log import InteractionRecord
from log_reader import HFLogReader, LocalReader, ReadReport
from sentinel import METRIC_GLOSSARY, METRIC_SPECS, THEMATIC_BLOCKS


def _record_dict(timestamp: str | None = None, event_type: str = "answered", total_latency: int = 1000) -> dict:
    return {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "session_id": "sess-x",
        "turn_index": 0,
        "question": "q?",
        "event_type": event_type,
        "branch": "GENERIC",
        "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": total_latency},
        "knew_answer": True,
    }


def test_data_history_days_returns_zero_for_empty_records():
    """No records → 0 days history. Defaults the muting check to 'mute'."""
    from sentinel import _data_history_days

    assert _data_history_days([]) == 0


def test_data_history_days_returns_span_in_days():
    """Span is max-timestamp − min-timestamp in calendar days, computed off
    the date prefix of each ISO timestamp (time-of-day is irrelevant for the
    14-day gate)."""
    from datetime import datetime, timedelta, timezone
    from interaction_log import InteractionRecord
    from sentinel import _data_history_days

    now = datetime.now(timezone.utc)
    rs = [
        InteractionRecord.model_validate({**_record_dict(), "timestamp": (now - timedelta(days=10)).isoformat()}),
        InteractionRecord.model_validate({**_record_dict(), "timestamp": now.isoformat()}),
    ]
    assert _data_history_days(rs) == 10


def test_global_window_appears_in_window_set_and_today_does_not():
    """Per issue #35: WINDOWS = [(Global, None), (30d, 30), (7d, 7)] — Today removed
    (low signal in low-traffic regime), Global added (first-glance all-time picture)."""
    from sentinel import WINDOWS

    labels = [label for label, _ in WINDOWS]
    assert "Global" in labels
    assert "Today" not in labels
    # Global maps to days=None (no filter)
    global_days = dict(WINDOWS)["Global"]
    assert global_days is None


def test_thematic_blocks_partition_every_plottable_metric_exactly_once():
    """THEMATIC_BLOCKS maps Panel-1's 5 blocks (Outcome / Routing / Engagement / Tool use /
    Latency) to lists of metric names; every plottable metric appears in exactly one block.
    Forcing function: adding a metric to METRIC_GETTERS forces an entry in THEMATIC_BLOCKS."""
    all_assigned = [m for metrics in THEMATIC_BLOCKS.values() for m in metrics]
    assert sorted(all_assigned) == sorted(METRIC_GETTERS.keys()), (
        "THEMATIC_BLOCKS must enumerate every plottable metric (no duplicates, no omissions)"
    )
    assert sorted(all_assigned) == sorted(set(all_assigned)), "no metric in two blocks"
    # Five blocks, matching Panel 1's headings
    assert set(THEMATIC_BLOCKS.keys()) == {
        "Outcome", "Routing", "Engagement", "Tool use", "Latency"
    }


def test_is_stale_treats_missing_file_as_stale(tmp_path):
    """Missing file → stale. Forces a first-run population on launch."""
    from sentinel import is_stale

    assert is_stale(tmp_path / "absent.json") is True


def test_is_stale_treats_recent_file_as_fresh(tmp_path):
    """Files younger than the freshness window are fresh — boot fast on the
    second launch in the same week."""
    from sentinel import is_stale

    p = tmp_path / "recent.json"
    p.write_text("{}")  # mtime = now
    assert is_stale(p, max_age_days=7) is False


def test_is_stale_treats_old_file_as_stale(tmp_path):
    """Files older than the freshness window are stale — forces a refresh on
    the next launch so the dashboard never silently shows week-old data."""
    import os
    from datetime import datetime, timedelta, timezone
    from sentinel import is_stale

    p = tmp_path / "old.json"
    p.write_text("{}")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(p, (old, old))
    assert is_stale(p, max_age_days=7) is True


def test_ensure_fresh_clusters_skips_when_cache_is_fresh(tmp_path, monkeypatch):
    """When the cluster file is fresh the helper must NOT call the LLM batch
    — that's the whole point of caching."""
    from sentinel import ensure_fresh_clusters

    fresh = tmp_path / "gap_clusters.json"
    fresh.write_text("{}")

    called = []
    monkeypatch.setattr(
        "sentinel.cluster_gaps.run_batch",
        lambda **kw: called.append(kw),
    )
    msg = ensure_fresh_clusters(out_path=fresh, max_age_days=7)
    assert msg is None
    assert called == [], "fresh cache must not trigger the batch"


def test_ensure_fresh_clusters_runs_batch_when_cache_missing(tmp_path, monkeypatch):
    """Missing cache → call the LLM batch. Returns None on success (the boot
    banner stays empty)."""
    from sentinel import ensure_fresh_clusters

    out = tmp_path / "gap_clusters.json"
    archive = tmp_path / "archive"

    called = []
    monkeypatch.setattr(
        "sentinel.cluster_gaps.run_batch",
        lambda **kw: called.append(kw),
    )
    msg = ensure_fresh_clusters(out_path=out, archive_dir=archive, max_age_days=7)
    assert msg is None
    assert len(called) == 1
    assert called[0]["out_path"] == out


def test_ensure_fresh_clusters_returns_loud_error_when_batch_fails(tmp_path, monkeypatch):
    """LLM unreachable / no API key → return an error string. Sentinel renders
    this as a banner so the operator knows the dashboard is operating on stale
    data instead of silently shipping it."""
    from sentinel import ensure_fresh_clusters

    out = tmp_path / "gap_clusters.json"

    def _boom(**kw):
        raise RuntimeError("OPENAI_API_KEY missing")

    monkeypatch.setattr("sentinel.cluster_gaps.run_batch", _boom)
    msg = ensure_fresh_clusters(out_path=out, max_age_days=7)
    assert msg is not None
    assert "Cluster" in msg
    assert "OPENAI_API_KEY" in msg


def test_ensure_fresh_summaries_returns_loud_error_when_batch_fails(tmp_path, monkeypatch):
    """Same loud-failure contract as ensure_fresh_clusters — "cache silently
    stale" is exactly the failure mode Sentinel exists to prevent."""
    from sentinel import ensure_fresh_summaries

    def _boom(**kw):
        raise RuntimeError("rate limited")

    monkeypatch.setattr("sentinel.summarize_failures.run_batch", _boom)
    msg = ensure_fresh_summaries(out_dir=tmp_path / "summaries", max_age_days=7)
    assert msg is not None
    assert "Summary" in msg
    assert "rate limited" in msg


def test_metric_glossary_keys_match_metric_specs_labels():
    """Forcing function: every row label in METRIC_SPECS must have a glossary
    entry, and the glossary must not carry orphan keys for labels that don't
    exist on the dashboard. Catches drift on label rename without coupling
    tests to prose."""
    spec_labels = {label for _, specs in METRIC_SPECS for (label, *_) in specs}
    glossary_labels = set(METRIC_GLOSSARY.keys())

    missing = spec_labels - glossary_labels
    orphan = glossary_labels - spec_labels
    assert not missing, f"glossary missing entries for: {sorted(missing)}"
    assert not orphan, f"glossary has orphan entries: {sorted(orphan)}"


def test_row_severity_tier_b_returns_orientation_when_history_below_gate():
    """Tier B shift-on-band requires >=14 days of data history. Below the
    gate, the row falls through to orientation (no badge) rather than firing
    cold-start spurious alerts on tight window overlap. Mirrors the existing
    delta-mute gate _delta_inline applies."""
    from sentinel import _row_severity

    # Three raws that WOULD trigger an alert (440% relative change 7d→30d)
    # if the gate didn't fire.
    raws = [1.0, 0.185, 0.058]

    # Below 14-day gate → orientation
    assert _row_severity("gap_rate", raws, history_days=10) == "orientation"
    # At/above 14-day gate → alert (the shift fires)
    assert _row_severity("gap_rate", raws, history_days=14) == "alert"
    assert _row_severity("gap_rate", raws, history_days=30) == "alert"


def test_row_severity_tier_b_default_history_zero_treats_as_below_gate():
    """Default history_days=0 keeps Tier B suppressed — important because
    callers that forget to pass history_days shouldn't accidentally surface
    spurious shift alerts."""
    from sentinel import _row_severity

    raws = [1.0, 0.185, 0.058]  # would fire alert if gate disabled
    assert _row_severity("gap_rate", raws) == "orientation"


def test_row_severity_tier_a_unaffected_by_history_gate():
    """Tier A value-on-band semantics don't depend on data history (a
    refusal rate above 3% is a failure regardless of how long the log
    spans). Gate must NOT suppress Tier A."""
    from sentinel import _row_severity

    # 4 refused records → refusal_rate well above 3% warning band → alert
    raws = [1.0, 1.0, 1.0]
    assert _row_severity("refusal_rate", raws, history_days=0) == "alert"
    assert _row_severity("refusal_rate", raws, history_days=10) == "alert"


def _make_record(tmp_path: Path, *, session_id: str, is_canary: bool, ts: str):
    """Helper — build a minimal InteractionRecord-shaped dict and write it.
    Mirrors the shape of records produced by Pipeline.run; only the fields
    required by the reader path are populated."""
    return {
        "schema_version": "4",
        "timestamp": ts,
        "session_id": session_id,
        "turn_index": 0,
        "question": "stub",
        "event_type": "answered",
        "branch": "GENERIC",
        "classifier_labels": ["GENERIC"],
        "classification_confidence": 1.0,
        "attempts": [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"total": 1, "classifier": 1, "retrieval": 0, "generation": 0, "guardrail": 0},
        "knew_answer": True,
        "is_canary": is_canary,
    }


def test_default_reader_wraps_hf_with_local_canary_overlay(monkeypatch, tmp_path):
    """When HF env is set, _default_reader() returns the dual-source wrapper
    so today's local canary records appear alongside live HF records."""
    from sentinel import _default_reader, _HFWithLocalCanaryOverlay

    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("HF_DATASET_REPO", "ignored/repo")
    # Stub HFLogReader so make_log_reader() can construct without a network call.
    from unittest.mock import MagicMock

    monkeypatch.setattr("log_reader.HFLogReader.__init__", lambda self, **kw: None)
    reader = _default_reader()
    assert isinstance(reader, _HFWithLocalCanaryOverlay)


def test_default_reader_does_not_wrap_when_local(monkeypatch):
    """In local mode the LocalReader already includes canary records, so the
    wrapper is unnecessary — _default_reader returns the LocalReader directly."""
    from sentinel import _default_reader, _HFWithLocalCanaryOverlay

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)
    reader = _default_reader()
    assert not isinstance(reader, _HFWithLocalCanaryOverlay)
    assert isinstance(reader, LocalReader)


def test_overlay_merges_hf_live_with_local_canary_only(tmp_path):
    """The wrapper returns HF-live records as-is plus only the is_canary=True
    records from the local file. Live records on the local file are dropped
    so they cannot double-count against records already on HF."""
    from sentinel import _HFWithLocalCanaryOverlay
    from unittest.mock import MagicMock

    # Build a local JSONL with one canary + one stale-live record
    local_file = tmp_path / "interactions.jsonl"
    records = [
        _make_record(tmp_path, session_id="local-canary", is_canary=True, ts="2026-05-07T01:00:00+00:00"),
        _make_record(tmp_path, session_id="stale-live", is_canary=False, ts="2026-05-06T23:00:00+00:00"),
    ]
    with local_file.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    # Fake the HF reader returning one live record
    hf = MagicMock()
    hf_record = InteractionRecord.model_validate(
        _make_record(tmp_path, session_id="hf-live", is_canary=False, ts="2026-05-07T02:00:00+00:00")
    )
    hf.read.return_value = [hf_record]

    wrapper = _HFWithLocalCanaryOverlay(hf, local_path=local_file)
    out = wrapper.read()

    session_ids = {r.session_id for r in out}
    assert "hf-live" in session_ids, "HF live records flow through"
    assert "local-canary" in session_ids, "local canary records overlaid"
    assert "stale-live" not in session_ids, "local non-canary records must be dropped"


def test_wrap_helper_wraps_hf_passes_through_local(monkeypatch):
    """The CLI path bypasses _default_reader and constructs the reader
    inline, so the overlay-wrapping logic must live in a helper that the
    CLI can reach. Regression for the bug where Sentinel-from-CLI showed
    plain HF Dataset records and the Canary tab read empty."""
    from sentinel import _wrap_with_canary_overlay_if_hf, _HFWithLocalCanaryOverlay
    from unittest.mock import MagicMock

    # HFLogReader → wrapped
    monkeypatch.setattr("log_reader.HFLogReader.__init__", lambda self, **kw: None)
    from log_reader import HFLogReader

    hf = HFLogReader()
    wrapped = _wrap_with_canary_overlay_if_hf(hf)
    assert isinstance(wrapped, _HFWithLocalCanaryOverlay)

    # LocalReader → pass-through (canary records are already in the local file)
    local = LocalReader(Path("/nonexistent"))
    assert _wrap_with_canary_overlay_if_hf(local) is local

    # Some other reader (e.g. test mock) → pass-through
    mock = MagicMock()
    assert _wrap_with_canary_overlay_if_hf(mock) is mock


# ---- Page model (issue #61) ---------------------------------------------------


NOW = datetime.now(timezone.utc)


def _live(*, days_ago: float = 1, question: str = "q?", event_type: str = "answered",
          branch: str = "GENERIC", session_id: str = "s1", turn_index: int = 0,
          attempts=None, contact_offered: bool = False, chunks=None, tool_calls=None) -> InteractionRecord:
    return InteractionRecord.model_validate({
        "schema_version": "4",
        "timestamp": (NOW - timedelta(days=days_ago)).isoformat(),
        "session_id": session_id, "turn_index": turn_index, "question": question,
        "event_type": event_type, "branch": branch, "classifier_labels": [branch],
        "classification_confidence": 0.9,
        "attempts": attempts or [{"answer": "ok", "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": chunks or [], "tool_calls": tool_calls or [],
        "latency_ms": {"classifier": 100, "retrieval": 200, "generation": 300, "guardrail": 400, "total": 1000},
        "knew_answer": True, "contact_offered": contact_offered,
    })


class _Reader:
    """A local-log reader holding records in memory."""

    def __init__(self, records, report=None):
        self._records = records
        self.report = report or ReadReport(files_read=1)

    def read(self, days=None):
        return list(self._records)


def _page(reader, tmp_path, **kw):
    from sentinel import build_page

    kw.setdefault("provided_session_ids", frozenset())
    kw.setdefault("outcomes_path", tmp_path / "outcomes.jsonl")
    return build_page(
        reader, verdicts_dir=tmp_path / "verdicts", baseline_path=tmp_path / "baseline.json",
        corpus_path=tmp_path / "corpus.json", clusters_path=tmp_path / "clusters.json",
        summaries_dir=tmp_path / "summaries", **kw,
    )


def _row(page, label):
    return next(r for s in page["metrics"] for r in s["rows"] if r["label"] == label)


def _hub(files: dict[str, list[dict]]) -> MagicMock:
    import tempfile

    api = MagicMock()
    api.list_repo_files = MagicMock(return_value=list(files))

    def download(*, repo_id, filename, repo_type):  # noqa: ARG001
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("".join(json.dumps(r) + "\n" for r in files[filename]))
        f.close()
        return f.name

    api.hf_hub_download = MagicMock(side_effect=download)
    return api


def _raw(days_ago: float = 1, **kw) -> dict:
    return json.loads(_live(days_ago=days_ago, **kw).model_dump_json())


def test_a_failed_dataset_listing_gives_a_red_page_with_the_reason_and_no_numbers(tmp_path, monkeypatch):
    from sentinel import _HFWithLocalCanaryOverlay, render

    api = _hub({})
    api.list_repo_files = MagicMock(side_effect=OSError("401 Unauthorized"))
    reader = _HFWithLocalCanaryOverlay(HFLogReader("ignored/test", hf_api=api), local_path=tmp_path / "none.jsonl")

    page = _page(reader, tmp_path)
    html = render(page)

    assert "401 Unauthorized" in page["failed"]
    assert "metrics" not in page
    assert "Log read failed" in html and "401 Unauthorized" in html
    assert "%" not in html.split("<body>")[1], "no figure may appear on a failed read"


def test_a_failed_day_download_gives_a_red_page_rather_than_a_smaller_total(tmp_path):
    from sentinel import render

    day = (NOW - timedelta(days=1)).date().isoformat()
    api = _hub({f"logs/{day}.jsonl": [_raw()]})
    api.hf_hub_download = MagicMock(side_effect=OSError("502 Bad Gateway"))

    page = _page(HFLogReader("ignored/test", hf_api=api), tmp_path)

    assert "502 Bad Gateway" in page["failed"] and day in page["failed"]
    assert "Log read failed" in render(page)


def test_without_a_token_the_page_says_it_reads_the_local_log(tmp_path, monkeypatch):
    from sentinel import _default_reader

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)
    assert isinstance(_default_reader(), LocalReader)

    page = _page(_Reader([_live()]), tmp_path)

    assert page["source"]["label"] == "Local log"
    assert page["source"]["production"] is False
    assert page["writer"] is None


def test_unreadable_lines_and_repeated_records_are_counted_on_the_page(tmp_path):
    log = tmp_path / "interactions.jsonl"
    row = _live().model_dump_json()
    log.write_text(row + "\n" + row + "\n" + "{truncated\n")

    page = _page(LocalReader(log), tmp_path)

    assert page["source"]["unreadable_lines"] == [f"{log}:3"]
    assert page["source"]["duplicates"] == 1
    assert page["source"]["records"] == 2


def test_production_read_reports_files_read_and_the_newest_record(tmp_path, monkeypatch):
    from sentinel import _HFWithLocalCanaryOverlay

    monkeypatch.setattr("hf_log_writer.read_writer_state", lambda api, *, repo_id: None)
    d1, d2 = ((NOW - timedelta(days=n)).date().isoformat() for n in (3, 1))
    api = _hub({f"logs/{d1}.jsonl": [_raw(days_ago=3)], f"logs/{d2}.jsonl": [_raw(days_ago=1, turn_index=1)]})
    reader = _HFWithLocalCanaryOverlay(HFLogReader("ignored/test", hf_api=api), local_path=tmp_path / "none.jsonl")

    page = _page(reader, tmp_path)

    assert page["source"]["label"] == "Production log"
    assert page["source"]["files_read"] == 2
    assert page["source"]["records"] == 2
    newest = datetime.fromisoformat(page["source"]["newest"])
    assert abs((NOW - timedelta(days=1)) - newest) < timedelta(seconds=5)


def test_a_writer_that_stopped_writing_shows_its_last_flush_and_no_error(tmp_path, monkeypatch):
    """Lateness is never an error: a writer silent for 40 days shows its
    last flush time (the page renders it as an age), not a red mark."""
    stopped = (NOW - timedelta(days=40)).isoformat()
    monkeypatch.setattr("hf_log_writer.read_writer_state",
                        lambda api, *, repo_id: {"last_flush_time": stopped, "buffer_size": 0, "last_error": None})

    page = _page(HFLogReader("ignored/test", hf_api=_hub({})), tmp_path)

    assert page["writer"]["last_flush_time"] == stopped
    assert page["writer"]["last_error"] is None


def test_a_writer_error_or_a_missing_state_file_is_reported_as_the_writers_error(tmp_path, monkeypatch):
    monkeypatch.setattr("hf_log_writer.read_writer_state",
                        lambda api, *, repo_id: {"last_flush_time": None, "buffer_size": 3,
                                                 "last_error": "RuntimeError: hf is down"})
    assert _page(HFLogReader("x/y", hf_api=_hub({})), tmp_path)["writer"]["last_error"] == "RuntimeError: hf is down"

    monkeypatch.setattr("hf_log_writer.read_writer_state", lambda api, *, repo_id: None)
    assert "never flushed" in _page(HFLogReader("x/y", hf_api=_hub({})), tmp_path)["writer"]["last_error"]


def test_all_time_has_no_change_vs_prior_while_30_days_compares_with_the_30_before(tmp_path):
    """Worked example: last 30 days hold one refusal in two turns (50%);
    the 30 days before hold one answered turn (0%). All time has no
    earlier window, so it shows no change."""
    records = [
        _live(days_ago=2, event_type="refused", session_id="a"),
        _live(days_ago=10, session_id="b"),
        _live(days_ago=45, session_id="c"),
    ]
    row = _row(_page(_Reader(records), tmp_path), "Refusal rate")

    assert [c["text"] for c in row["cells"]] == ["100.0%", "50.0%", "33.3%", "33.3%"]
    assert row["cells"][1]["delta"] == "+50.0 pp"
    assert "delta" not in row["cells"][3]


def test_contact_conversion_by_branch_counts_the_contact_submissions(tmp_path):
    """Session a (Gap branch) was offered the form and submitted it; the
    submission lives in the contacts file, not on the record."""
    records = [_live(branch="GAP", session_id="a", contact_offered=True),
               _live(branch="TECHNICAL", session_id="b", contact_offered=True)]
    page = _page(_Reader(records), tmp_path, provided_session_ids=frozenset({"a"}))

    by = {b["branch"]: b["values"][3] for b in _row(page, "Contact-conversion rate")["by_branch"]}

    assert by["Gap"] == {"text": "100.0%", "n": 1}
    assert by["Technical"] == {"text": "0.0%", "n": 1}
    assert by["Generic"] == {"text": "–", "n": 0}


def test_each_metric_row_says_what_it_measures_and_how_it_is_marked(tmp_path):
    page = _page(_Reader([_live()]), tmp_path)

    refusal = _row(page, "Refusal rate")
    assert "canned refusal" in refusal["about"]
    assert refusal["rule"] == "Judged on its value: healthy at 1% or less, a warning up to 3%, an alert above."
    assert _row(page, "Gap rate")["rule"].startswith("Judged on movement: a warning when it moves 7%")
    assert _row(page, "Unique sessions")["rule"].startswith("Not marked")


def test_failures_list_every_failing_turn_worst_kind_first_then_newest(tmp_path):
    records = [_live(days_ago=d, event_type="deflected", session_id=f"d{d}", question=f"deflected {d}")
               for d in range(1, 36)]
    records.append(_live(days_ago=20, event_type="refused", session_id="r", question="refused one"))

    rows = _page(_Reader(records), tmp_path)["failures"]

    assert len(rows) == 36, "no cap: every failing turn is listed"
    assert rows[0]["question"] == "refused one"
    assert [r["question"] for r in rows[1:3]] == ["deflected 1", "deflected 2"]


def test_a_failure_row_carries_its_attempts_sections_tools_latency_and_session(tmp_path):
    first = _live(days_ago=1.1, session_id="s", turn_index=0, question="first turn")
    bad = _live(days_ago=1, session_id="s", turn_index=1, question="second turn",
                attempts=[{"answer": "guess", "is_acceptable": False, "guardrail_feedback": "made up"},
                          {"answer": "fixed", "is_acceptable": True, "guardrail_feedback": ""}],
                chunks=[{"source_file": "skills.md", "section_heading": "Cloud"}],
                tool_calls=[{"name": "fetch_project_readme", "args": {}, "status": "success"}])

    row = _page(_Reader([first, bad]), tmp_path)["failures"][0]

    assert row["mode"] == "rejected-then-recovered"
    assert row["attempts"][0] == {"ok": False, "answer": "guess", "feedback": "made up"}
    assert row["chunks"] == ["skills.md · Cloud"]
    assert row["tools"] == ["fetch_project_readme · success"]
    assert row["latency"]["total"] == 1000
    assert [(t["turn"], t["self"]) for t in row["session"]] == [(0, False), (1, True)]


def test_a_turn_that_failed_before_the_retry_loop_is_a_refusal_with_its_stage_and_error(tmp_path):
    """An answered turn plus one whose classifier raised (#64) give a 50% 7-day refusal rate, the failed turn heading the Failures tab with its stage and error."""
    failed = InteractionRecord.model_validate({
        "schema_version": "5", "timestamp": (NOW - timedelta(days=1)).isoformat(),
        "session_id": "f", "turn_index": 0, "question": "Where does he live?",
        "event_type": "refused", "branch": "UNROUTED", "classifier_labels": [],
        "classification_confidence": 0.0, "attempts": [], "retrieved_chunks": [],
        "latency_ms": {"classifier": 1200, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 1201},
        "knew_answer": False, "failed_stage": "classifier", "error_type": "NotFoundError",
        "error_message": "model_not_found",
    })
    page = _page(_Reader([_live(days_ago=2, session_id="a"), failed]), tmp_path)

    assert _row(page, "Refusal rate")["cells"][0]["text"] == "50.0%"
    row = page["failures"][0]
    assert row["question"] == "Where does he live?"
    assert row["mode"] == "refused" and row["tier"] == "failure"
    assert row["error"] == "classifier: NotFoundError: model_not_found"
    assert row["attempts"] == []


def _canary_rec(question: str, run_id: str, rep: int, *, total_ms: int = 1000,
                days_ago: int = 0, answer: str = "ok"):
    return InteractionRecord.model_validate({
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
        "session_id": "canary", "turn_index": rep, "question": question,
        "event_type": "answered", "branch": "GENERIC",
        "classification_confidence": 0.9,
        "attempts": [{"answer": answer, "is_acceptable": True}],
        "retrieved_chunks": [], "tool_calls": [],
        "latency_ms": {"total": total_ms}, "knew_answer": True,
        "is_canary": True, "run_id": run_id, "replicate_index": rep,
        "git_sha": "abcdef1234",
    })


def _write_verdicts(verdicts_dir, run_id, rows):
    from canary_verdicts import ReplicateVerdict, write_run_verdicts
    write_run_verdicts(run_id, [
        ReplicateVerdict(question_id=qid, question=q, replicate_index=rep,
                         passed=ok, reason=reason, answer=f"answer {qid} {rep}")
        for qid, q, rep, ok, reason in rows
    ], verdicts_dir)


def test_canary_lists_failing_questions_first_with_the_judges_reason_and_answers(tmp_path):
    run = "run-20261120-010000-aaaaaa"
    records = [_canary_rec(q, run, i) for q in ("q1", "q2") for i in range(2)]
    _write_verdicts(tmp_path / "verdicts", run, [
        ("C001", "q1", 0, True, "fine"), ("C001", "q1", 1, True, "fine"),
        ("C002", "q2", 0, True, "fine"), ("C002", "q2", 1, False, "Says it has no information."),
    ])
    (tmp_path / "corpus.json").write_text(json.dumps([
        {"id": "C002", "question": "q2", "expected_behaviour": "Answers q2.", "category": "temporal"}]))

    c = _page(_Reader(records), tmp_path)["canary"]

    assert [q["id"] for q in c["questions"]] == ["C002", "C001"]
    q = c["questions"][0]
    assert (q["status"], q["judge"], q["category"], q["expected"]) == (
        "fail", "Says it has no information.", "Dates", "Answers q2.")
    assert [(r["i"], r["passed"], r["answer"]) for r in q["replicates"]] == [
        (0, True, "answer C002 0"), (1, False, "answer C002 1")]
    assert c["questions"][1]["judge"] == "2 of 2 pass"


def test_canary_marks_a_passing_question_slow_and_lists_every_run_since_the_baseline(tmp_path):
    """Over 1.5x the baseline median marks a passing question slow. Every run
    from the baseline on is listed, including one stopped part-way."""
    from canary_baseline import freeze_baseline

    base, stopped, latest = ("run-20261001-010000-bbbbbb", "run-20261101-010000-cccccc",
                             "run-20261120-010000-aaaaaa")
    freeze_baseline(base, frozen_git_sha="abc", path=tmp_path / "baseline.json")
    records = [_canary_rec("q1", base, 0, total_ms=1000, days_ago=30),
               _canary_rec("q1", stopped, 0, total_ms=1500, days_ago=10),
               _canary_rec("q1", latest, 0, total_ms=2000)]
    _write_verdicts(tmp_path / "verdicts", latest, [("C001", "q1", 0, True, "fine")])

    c = _page(_Reader(records), tmp_path)["canary"]

    assert c["questions"][0]["status"] == "slow"
    assert (c["questions"][0]["base"], c["questions"][0]["now"]) == ("1.0 s", "2.0 s")
    assert [r["id"] for r in c["runs"]] == [base, stopped, latest]
    assert [r["baseline"] for r in c["runs"]] == [True, False, False]
    assert (c["runs"][1]["records"], c["runs"][1]["q_n"]) == (1, None), "stopped run, not judged"
    assert (c["runs"][2]["q_pass"], c["runs"][2]["r_pass"], c["runs"][2]["p95"]["total"]) == (1, 1, "2.00 s")


def test_canary_with_an_unjudged_latest_run_says_so_and_with_no_runs_is_empty(tmp_path):
    run = "run-20261120-010000-aaaaaa"
    c = _page(_Reader([_canary_rec("q1", run, 0)]), tmp_path)["canary"]
    assert c["judged"] is False and c["latest"] == run

    assert _page(_Reader([_live()]), tmp_path)["canary"] is None


def test_coverage_lists_every_knowledge_base_section_with_its_retrievals(tmp_path):
    from kb_corpus import load_sections

    sections = load_sections()
    hit = sections[0]
    records = [_live(chunks=[{"source_file": hit.source_file, "section_heading": hit.section_heading},
                             {"source_file": "education.md", "section_heading": "Removed section"}])]

    cov = {(e["file"], e["section"]): e for e in _page(_Reader(records), tmp_path)["coverage"]}

    assert len(cov) == len(sections) + 1
    assert cov[(hit.source_file, hit.section_heading)] == {
        "section": hit.section_heading, "file": hit.source_file, "count": 1, "off": False}
    assert cov[("education.md", "Removed section")]["off"] is True
    assert cov[(sections[1].source_file, sections[1].section_heading)]["count"] == 0


def test_cached_gap_clusters_and_deflection_summary_show_on_production_pages_only(tmp_path, monkeypatch):
    (tmp_path / "clusters.json").write_text(json.dumps(
        {"generated_at": NOW.isoformat(), "period_days": 7,
         "clusters": [{"label": "Cloud", "count": 2, "examples": ["AWS?"]}]}))
    (tmp_path / "summaries").mkdir()
    (tmp_path / "summaries" / "deflection_2026-11-20.md").write_text("# Deflection summary\n\nTwo jokes.")

    monkeypatch.setattr("hf_log_writer.read_writer_state", lambda api, *, repo_id: None)
    day = (NOW - timedelta(days=1)).date().isoformat()
    production = _page(HFLogReader("x/y", hf_api=_hub({f"logs/{day}.jsonl": [_raw()]})), tmp_path)
    local = _page(_Reader([_live()]), tmp_path)

    assert production["clusters"]["clusters"][0]["label"] == "Cloud"
    assert "Two jokes." in production["deflection"]
    assert (local["clusters"], local["deflection"]) == (None, None), "they describe production"


def test_the_rendered_page_carries_the_page_data(tmp_path):
    from sentinel import render

    question = "Do you know </script><b>Rust</b>?"
    page = _page(_Reader([_live(event_type="gap", question=question)]), tmp_path)
    html = render(page)

    assert "/*__DATA__*/null" not in html
    assert "</script><b>" not in html, "a question cannot close the data script"
    data = json.loads(html.split("const D = ", 1)[1].split(";\nconst READ", 1)[0])
    assert data["failures"][0]["question"] == question


def _main_env(tmp_path, monkeypatch):
    import sentinel

    monkeypatch.setattr(sentinel, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(sentinel, "PAGE_PATH", tmp_path / "sentinel.html")
    monkeypatch.setattr(sentinel, "CLUSTERS_DEFAULT_PATH", tmp_path / "clusters.json")
    monkeypatch.setattr(sentinel, "CLUSTERS_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(sentinel, "DEFAULT_SUMMARIES_DIR", tmp_path / "summaries")
    monkeypatch.setattr(sentinel, "DEFAULT_OUTCOMES_PATH", tmp_path / "outcomes.jsonl")
    opened = []
    monkeypatch.setattr(sentinel.webbrowser, "open", opened.append)
    return sentinel, opened


def test_main_on_the_local_log_writes_the_page_and_leaves_the_production_caches_alone(tmp_path, monkeypatch):
    """--local reads the local log and never rebuilds the cluster and summary
    caches, which describe production."""
    sentinel, opened = _main_env(tmp_path, monkeypatch)
    log = tmp_path / "interactions.jsonl"
    log.write_text(_live(event_type="gap", question="hello there").model_dump_json() + "\n")
    monkeypatch.setattr(sentinel, "make_log_reader", lambda force_local=False: LocalReader(log))

    path = sentinel.main(["--local", "--no-open"])

    assert path == tmp_path / "sentinel.html" and opened == []
    assert "hello there" in path.read_text()
    assert not (tmp_path / "clusters.json").exists() and not (tmp_path / "summaries").exists()


def test_main_on_production_reports_a_cache_batch_whose_model_call_failed(tmp_path, monkeypatch):
    """Production run, hub and model faked at the process boundary: the
    batch failure shows on the page with its cause, not tenacity's wrapper."""
    import cluster_gaps
    import summarize_failures

    sentinel, _ = _main_env(tmp_path, monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("HF_DATASET_REPO", "ignored/repo")
    day = (NOW - timedelta(days=1)).date().isoformat()
    hub = _hub({f"logs/{day}.jsonl": [_raw(event_type="gap", question="hello there")]})
    monkeypatch.setattr("huggingface_hub.HfApi", lambda token=None: hub)
    monkeypatch.setattr("hf_contact_log.HfApi", lambda token=None: hub)
    monkeypatch.setattr("hf_log_writer.read_writer_state", lambda api, *, repo_id: None)
    monkeypatch.setattr(sentinel, "DEFAULT_LOG_PATH", tmp_path / "no-local-canaries.jsonl")

    def model_down(**kw):
        raise RuntimeError("model down")

    import outcome_judge

    monkeypatch.setattr(cluster_gaps, "completion", model_down)
    monkeypatch.setattr(summarize_failures, "completion", model_down)
    monkeypatch.setattr(outcome_judge, "completion", model_down)
    monkeypatch.setattr(outcome_judge, "JUDGE_RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(cluster_gaps.GapClusterer.cluster.retry, "sleep", lambda seconds: None)
    monkeypatch.setattr(summarize_failures.FailureSummarizer.summarize.retry, "sleep", lambda seconds: None)

    html = sentinel.main(["--no-open"]).read_text()

    assert "hello there" in html
    assert "Summary batch failed: RuntimeError: model down" in html
    assert "Outcome judge could not label 1 turn (they show as not yet judged): RuntimeError: model down" in html


def test_a_failed_contacts_read_gives_the_red_page_too(tmp_path, monkeypatch):
    """Conversion joins on the contact submissions; reading them partly
    would show a quiet 0%, so their failure fails the page like the log's."""
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("HF_DATASET_REPO", "ignored/repo")
    contacts_api = _hub({})
    contacts_api.list_repo_files = MagicMock(side_effect=OSError("contacts listing down"))
    monkeypatch.setattr("hf_contact_log.HfApi", lambda token=None: contacts_api)
    monkeypatch.setattr("hf_log_writer.read_writer_state", lambda api, *, repo_id: None)
    day = (NOW - timedelta(days=1)).date().isoformat()

    page = _page(HFLogReader("ignored/test", hf_api=_hub({f"logs/{day}.jsonl": [_raw()]})), tmp_path,
                 provided_session_ids=None)

    assert "contacts listing down" in page["failed"]


def test_the_local_log_is_joined_with_local_contacts_even_with_production_credentials(tmp_path, monkeypatch):
    """--local must not mix sources: production contacts are never read."""
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("HF_DATASET_REPO", "ignored/repo")
    production = MagicMock()
    production.list_repo_files = MagicMock(side_effect=AssertionError("production contacts were read"))
    monkeypatch.setattr("hf_contact_log.HfApi", lambda token=None: production)

    page = _page(_Reader([_live()]), tmp_path, provided_session_ids=None)

    assert page["failed"] is None
    production.list_repo_files.assert_not_called()


# ---- Every live turn is traffic (owner's ruling on #63, 2026-11-20) ----------


DEPLOY = NOW - timedelta(days=2)


def _turn(minutes: float, *, sha: str | None = "sha-new-1", question: str = "q?", session_id: str = "v",
          turn_index: int = 0, refused: bool = False, chunks=None, total_ms: int = 1000,
          event_type: str = "answered", branch: str = "GENERIC", answer: str = "ok",
          start=None) -> InteractionRecord:
    """A live turn ``minutes`` after ``start`` (default DEPLOY), logged under deploy ``sha``."""
    attempts = ([{"answer": "no", "is_acceptable": False, "guardrail_feedback": "x"}] * 3 if refused
                else [{"answer": answer, "is_acceptable": True, "guardrail_feedback": ""}])
    return InteractionRecord.model_validate({
        "schema_version": "4", "git_sha": sha,
        "timestamp": ((start or DEPLOY) + timedelta(minutes=minutes)).isoformat(),
        "session_id": session_id, "turn_index": turn_index, "question": question,
        "event_type": "refused" if refused else event_type, "branch": branch,
        "classifier_labels": [branch], "classification_confidence": 0.9, "attempts": attempts,
        "retrieved_chunks": [{"source_file": "skills.md", "section_heading": "Cloud"}] if chunks is None else chunks,
        "tool_calls": [],
        "latency_ms": {"classifier": 1, "retrieval": 1, "generation": 1, "guardrail": 1, "total": total_ms},
        "knew_answer": True,
    })


def test_every_live_turn_counts_whoever_sent_it(tmp_path):
    """Worked example (owner's ruling, 2026-11-20): a deploy's first turn at
    0 min, the owner's next check at 5 min, a placeholder turn with no
    retrieval and a 4 ms total, and a visitor at 61 min are all traffic: four
    turns in the totals, the Failures tab and Coverage. Only canary turns
    stay out."""
    records = [
        _turn(0, session_id="c", question="check one"),
        _turn(5, session_id="c", turn_index=1, refused=True, question="check refused"),
        _turn(6, sha=None, session_id="stub", chunks=[], total_ms=4, question="smoke"),
        _turn(61, session_id="v", question="visitor"),
        _turn(62, session_id="canary", question="canary").model_copy(update={"is_canary": True}),
    ]

    page = _page(_Reader(records), tmp_path)

    assert page["source"]["records"] == 4
    assert page["window_totals"] == [4, 4, 4, 4]
    assert _row(page, "Total interactions")["cells"][3]["text"] == "4"
    assert "check refused" in [f["question"] for f in page["failures"]]
    assert sum(e["count"] for e in page["coverage"]) == 3
    assert "deploy_check" not in page


# ---- Outcomes read from the answer (issue #63) --------------------------------


def _judged(tmp_path, labels: list):
    """Write the outcome cache as the judge would, from ``[(record, label)]``."""
    from outcome_judge import outcome_key

    (tmp_path / "outcomes.jsonl").write_text("".join(
        json.dumps({"key": outcome_key(r), "outcome": o}) + "\n" for r, o in labels))


def test_outcome_rates_come_from_the_judged_answer_over_judged_turns(tmp_path):
    """Worked example: "Where does he live?" answered "Melbourne" is logged as
    deflected by the logistical branch; the judge reads it as answered. A
    second turn is not judged yet, so the rates divide by one judged turn."""
    where = _turn(100, session_id="a", branch="LOGISTICAL", event_type="deflected",
                  question="Where does he live?", answer="Melbourne, Victoria, Australia.")
    later = _turn(200, session_id="b", event_type="gap")
    _judged(tmp_path, [(where, "answered")])

    page = _page(_Reader([where, later]), tmp_path)

    assert _row(page, "Answered with substance")["cells"][3]["text"] == "100.0%"
    assert _row(page, "Deflection rate")["cells"][3]["text"] == "0.0%"
    assert _row(page, "Gap rate")["cells"][3]["text"] == "0.0%"
    assert _row(page, "Not yet judged")["cells"][3]["text"] == "1"


def test_the_gap_rate_flag_reads_the_judged_outcome_like_the_gap_rate_row(tmp_path):
    """This week holds four gap-branch turns logged as gap that the judge
    read as answered, last week one answered turn: the logged label would
    jump 100 points, the judged gap rate does not move, so no flag."""
    this_week = [_turn(i, sha=None, session_id=f"g{i}", event_type="gap", start=NOW - timedelta(days=3))
                 for i in range(4)]
    last_week = _turn(0, sha=None, session_id="old", start=NOW - timedelta(days=10))
    _judged(tmp_path, [(r, "answered") for r in [*this_week, last_week]])

    page = _page(_Reader([*this_week, last_week]), tmp_path)

    assert page["source"]["records"] == 5
    assert _row(page, "Gap rate")["cells"][0]["text"] == "0.0%"
    assert not any(f["headline"].startswith("Gap rate jumped") for f in page["flags"])


def test_failures_show_the_judged_outcome_and_unjudged_turns_as_not_yet_judged(tmp_path):
    """A gap-branch answer with substance is no failure; an answered-logged
    "I don't have that" is did not know; a declined turn shows as declined."""
    gap_branch = _turn(100, session_id="a", event_type="gap", question="MTG projects?")
    no_info = _turn(110, session_id="b", question="Exact F1 score?")
    joke = _turn(120, session_id="c", event_type="deflected", question="Tell me a joke")
    unjudged = _turn(130, session_id="d", question="Fresh turn")
    _judged(tmp_path, [(gap_branch, "answered"), (no_info, "did not know"), (joke, "declined")])

    rows = {f["question"]: f for f in _page(_Reader([gap_branch, no_info, joke, unjudged]), tmp_path)["failures"]}

    assert set(rows) == {"Exact F1 score?", "Tell me a joke", "Fresh turn"}
    assert (rows["Exact F1 score?"]["mode"], rows["Exact F1 score?"]["outcome"]) == ("did-not-know", "did not know")
    assert rows["Tell me a joke"]["mode"] == "declined"
    assert (rows["Fresh turn"]["mode"], rows["Fresh turn"]["outcome"]) == ("not-judged", None)


def test_main_on_production_judges_new_turns_once_before_building_the_page(tmp_path, monkeypatch):
    """The judge model is faked: the production run labels the new turn and
    the page shows the label; a second run makes no further call."""
    import cluster_gaps
    import outcome_judge
    import summarize_failures

    sentinel, _ = _main_env(tmp_path, monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("HF_DATASET_REPO", "ignored/repo")
    day = (NOW - timedelta(days=1)).date().isoformat()
    hub = _hub({f"logs/{day}.jsonl": [_raw(event_type="gap", question="Any AWS?")]})
    monkeypatch.setattr("huggingface_hub.HfApi", lambda token=None: hub)
    monkeypatch.setattr("hf_contact_log.HfApi", lambda token=None: hub)
    monkeypatch.setattr("hf_log_writer.read_writer_state", lambda api, *, repo_id: None)
    monkeypatch.setattr(sentinel, "DEFAULT_LOG_PATH", tmp_path / "no-local-canaries.jsonl")
    monkeypatch.setattr(sentinel, "DEFAULT_OUTCOMES_PATH", tmp_path / "outcomes.jsonl")
    monkeypatch.setattr(cluster_gaps, "run_batch", lambda **kw: None)
    monkeypatch.setattr(summarize_failures, "run_batch", lambda **kw: None)
    calls = []

    def judge_model(**kw):
        calls.append(kw)
        return MagicMock(choices=[MagicMock(message=MagicMock(content='{"outcome": "did not know"}'))])

    monkeypatch.setattr(outcome_judge, "completion", judge_model)

    html = sentinel.main(["--no-open"]).read_text()
    sentinel.main(["--no-open"])

    assert len(calls) == 1
    assert '"outcome": "did not know"' in html

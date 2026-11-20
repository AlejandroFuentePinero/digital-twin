"""Tests for the live-turn outcome judge (issue #63). The judge model is the
process boundary and is faked; no LLM calls run in tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import outcome_judge
from interaction_log import InteractionRecord
from outcome_judge import judge_new_turns, outcome_key, read_outcomes
from pipeline import CANNED_REFUSAL


def _record(ts: str, *, question: str = "Where does he live?", answer: str | None = "Melbourne.") -> InteractionRecord:
    attempts = ([{"answer": answer, "is_acceptable": True}] if answer is not None
                else [{"answer": "draft", "is_acceptable": False}] * 3)
    return InteractionRecord(
        timestamp=ts, session_id="s", turn_index=0, question=question,
        event_type="answered" if answer is not None else "refused", branch="LOGISTICAL",
        classification_confidence=0.9, attempts=attempts, retrieved_chunks=[],
        latency_ms={"total": 1000}, knew_answer=True,
    )


def _says(outcome: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({"outcome": outcome})))])


def test_each_turn_is_judged_once_and_the_label_is_kept(tmp_path):
    """Two turns judged on the first run; the second run makes no call."""
    cache = tmp_path / "outcomes.jsonl"
    records = [_record("2026-11-20T01:00:00+00:00"), _record("2026-11-20T02:00:00+00:00", question="Favourite film?")]
    def model_reply(**kw):
        return _says("declined" if "Favourite film?" in kw["messages"][1]["content"] else "answered")

    with patch("outcome_judge.completion", side_effect=model_reply) as model:
        assert judge_new_turns(records, cache) is None
        assert judge_new_turns(records, cache) is None

    assert model.call_count == 2
    assert read_outcomes(cache) == {outcome_key(records[0]): "answered", outcome_key(records[1]): "declined"}


def test_the_judge_reads_the_answer_the_visitor_saw(tmp_path):
    """A refused turn is judged on the canned refusal, never on a rejected draft."""
    with patch("outcome_judge.completion", return_value=_says("error")) as model:
        judge_new_turns([_record("2026-11-20T01:00:00+00:00", answer=None)], tmp_path / "o.jsonl")

    prompt = model.call_args.kwargs["messages"][1]["content"]
    assert CANNED_REFUSAL in prompt and "draft" not in prompt
    assert "Where does he live?" in prompt


def test_a_failed_or_unreadable_judgement_leaves_the_turn_unjudged_and_says_so(tmp_path, monkeypatch):
    """Nothing is cached for a turn the judge could not label, so the next
    run tries it again, and the run reports how many failed."""
    monkeypatch.setattr(outcome_judge, "JUDGE_RETRY_WAIT_SECONDS", 0)
    cache = tmp_path / "o.jsonl"
    records = [_record("2026-11-20T01:00:00+00:00", question="Unreadable?"),
               _record("2026-11-20T02:00:00+00:00", question="Provider down?")]

    def model(**kw):
        if "Provider down?" in kw["messages"][1]["content"]:
            raise RuntimeError("rate limited")
        return _says("maybe")

    with patch("outcome_judge.completion", side_effect=model):
        message = judge_new_turns(records, cache)

    assert read_outcomes(cache) == {}
    assert message.startswith("Outcome judge could not label 2 turns")
    assert "rate limited" in message


def test_a_turn_that_failed_before_the_retry_loop_is_an_error_without_a_model_call(tmp_path):
    """A record carrying ``failed_stage`` (#64) had no answer to read."""
    failed = _record("2026-11-20T01:00:00+00:00", answer=None)
    object.__setattr__(failed, "failed_stage", "classifier")
    with patch("outcome_judge.completion") as model:
        judge_new_turns([failed], tmp_path / "o.jsonl")

    model.assert_not_called()
    assert read_outcomes(tmp_path / "o.jsonl") == {outcome_key(failed): "error"}


def test_no_cache_file_means_nothing_is_judged_yet(tmp_path):
    """A missing cache reads as no judgements."""
    assert read_outcomes(tmp_path / "absent.jsonl") == {}

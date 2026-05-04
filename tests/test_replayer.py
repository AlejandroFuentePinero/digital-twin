"""Tests for the Replay-from-record affordance (issue #38).

`replay()` calls real `Pipeline.run` against the current code; we mock at the
Pipeline boundary (per `docs/TESTING.md`'s "no LLM API calls in tests") via an
injectable `pipeline_factory`. The fake factory returns a fake Pipeline whose
`run()` method writes a synthetic record to the supplied log writer — same shape
as what the real Pipeline does, without the LLM round trip.
"""

from datetime import datetime, timezone

from interaction_log import InteractionRecord

from replayer import (
    CapturingLogWriter,
    ReplayResult,
    reconstruct_history,
    replay,
)


def _record(
    session_id: str = "sess-A",
    turn_index: int = 0,
    question: str = "q?",
    answer: str = "ok",
    branch: str = "GENERIC",
) -> InteractionRecord:
    return InteractionRecord.model_validate({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "turn_index": turn_index,
        "question": question,
        "event_type": "answered",
        "branch": branch,
        "classification_confidence": 1.0,
        "attempts": [{"answer": answer, "is_acceptable": True, "guardrail_feedback": ""}],
        "retrieved_chunks": [],
        "tool_calls": [],
        "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
        "knew_answer": True,
    })


class _FakeReader:
    """Stand-in for LocalReader that returns a fixed list of records."""
    def __init__(self, records: list[InteractionRecord]):
        self._records = records

    def read(self) -> list[InteractionRecord]:
        return list(self._records)


# ----- reconstruct_history ----------------------------------------------------


def test_reconstruct_history_returns_alternating_user_assistant_messages_for_prior_turns():
    """For a record at turn N, history is every prior turn (turn_index < N) in the same
    session, ordered ascending by turn_index, formatted as alternating
    {role: 'user', content: question} → {role: 'assistant', content: answer} pairs."""
    target = _record(session_id="s1", turn_index=2, question="third q")
    prior_turns = [
        _record(session_id="s1", turn_index=0, question="first q", answer="first a"),
        _record(session_id="s1", turn_index=1, question="second q", answer="second a"),
    ]
    history = reconstruct_history(target, _FakeReader([target] + prior_turns))

    assert history == [
        {"role": "user", "content": "first q"},
        {"role": "assistant", "content": "first a"},
        {"role": "user", "content": "second q"},
        {"role": "assistant", "content": "second a"},
    ]


def test_reconstruct_history_returns_empty_list_for_turn_zero():
    """A turn-0 record has no prior turns; replay still works against an empty history."""
    target = _record(session_id="s1", turn_index=0)
    history = reconstruct_history(target, _FakeReader([target]))
    assert history == []


def test_reconstruct_history_excludes_turns_from_other_sessions():
    """Reconstruction only includes the target's own session — concurrent sessions
    must not bleed history into each other or the replay context becomes incoherent."""
    target = _record(session_id="s1", turn_index=1, question="my second q")
    other_session_turn = _record(session_id="s2", turn_index=0, question="someone else's q")
    my_first_turn = _record(session_id="s1", turn_index=0, question="my first q", answer="my first a")

    history = reconstruct_history(
        target, _FakeReader([target, other_session_turn, my_first_turn])
    )
    assert history == [
        {"role": "user", "content": "my first q"},
        {"role": "assistant", "content": "my first a"},
    ]


# ----- replay -----------------------------------------------------------------


class _FakePipeline:
    """Stand-in for Pipeline. `run()` writes a synthetic 'fresh' record to the
    injected log_writer and stashes the call args for assertions."""

    def __init__(self, log_writer, fresh_branch: str = "TECHNICAL"):
        self._log_writer = log_writer
        self._fresh_branch = fresh_branch
        self.calls: list[dict] = []

    def run(self, *, question, history, session_id, turn_index, **kwargs):
        self.calls.append({
            "question": question,
            "history": history,
            "session_id": session_id,
            "turn_index": turn_index,
            **kwargs,
        })
        self._log_writer.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_index": turn_index,
            "question": question,
            "event_type": "answered",
            "branch": self._fresh_branch,
            "classification_confidence": 0.95,
            "attempts": [{"answer": "fresh answer", "is_acceptable": True, "guardrail_feedback": ""}],
            "retrieved_chunks": [],
            "tool_calls": [],
            "latency_ms": {"classifier": 1, "retrieval": 1, "generation": 1, "guardrail": 1, "total": 4},
            "knew_answer": True,
        })
        return "fresh answer"


def test_replay_calls_pipeline_with_original_question_and_reconstructed_history():
    """replay() forwards the record's question + the reconstructed prior history into
    Pipeline.run, preserving session_id and turn_index so the new record is comparable
    to the original under the same context."""
    target = _record(session_id="s1", turn_index=1, question="follow-up", answer="orig answer")
    prior = _record(session_id="s1", turn_index=0, question="opener", answer="opener answer")
    reader = _FakeReader([target, prior])

    captured_pipeline: list[_FakePipeline] = []

    def factory(*, log_writer):
        pipeline = _FakePipeline(log_writer)
        captured_pipeline.append(pipeline)
        return pipeline

    replay(target, reader=reader, pipeline_factory=factory)

    [pipeline] = captured_pipeline
    assert len(pipeline.calls) == 1
    call = pipeline.calls[0]
    assert call["question"] == "follow-up"
    assert call["session_id"] == "s1"
    assert call["turn_index"] == 1
    assert call["history"] == [
        {"role": "user", "content": "opener"},
        {"role": "assistant", "content": "opener answer"},
    ]


def test_replay_returns_replay_result_with_original_and_captured_records():
    """The captured ReplayResult holds the original record AND the freshly-generated record
    (the one Pipeline.run wrote to the capturing log writer) so the UI can render both."""
    target = _record(session_id="s1", turn_index=0, question="q?", answer="orig answer", branch="GENERIC")
    reader = _FakeReader([target])

    def factory(*, log_writer):
        return _FakePipeline(log_writer, fresh_branch="TECHNICAL")

    result = replay(target, reader=reader, pipeline_factory=factory)

    assert isinstance(result, ReplayResult)
    assert result.original is target
    assert result.current.branch == "TECHNICAL"
    assert result.current.attempts[-1]["answer"] == "fresh answer"
    assert result.current.classification_confidence == 0.95


def test_replay_raises_when_pipeline_did_not_emit_a_record():
    """If the pipeline runs without writing to the log writer, replay surfaces the bug
    as a clear error rather than returning a half-built ReplayResult with `current=None`."""

    class _SilentPipeline:
        def __init__(self, log_writer):
            self.log_writer = log_writer

        def run(self, **kwargs):
            return "noop"

    def factory(*, log_writer):
        return _SilentPipeline(log_writer)

    target = _record()
    import pytest
    with pytest.raises(RuntimeError, match="no record was captured"):
        replay(target, reader=_FakeReader([target]), pipeline_factory=factory)

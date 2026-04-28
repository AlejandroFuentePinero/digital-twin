"""
Tests for answer.py.

Strategy:
- Pure functions (merge_chunks, _format_context): no mocks needed
- Functions with LLM/DB calls: mock at the I/O boundary only, test the surrounding logic
- Focus on non-obvious correctness properties: guard logic, history threading,
  message structure, pipeline wiring
"""

from unittest.mock import MagicMock, patch

import pytest

from answer import (
    CANNED_REFUSAL,
    FINAL_K,
    MAX_RETRIES,
    Chunk,
    RankOrder,
    _format_context,
    _rerun,
    answer_question,
    answer_with_guardrail,
    fetch_context_unranked,
    make_rag_messages,
    merge_chunks,
    rerank,
    rewrite_query,
)


def make_chunk(content: str, source: str = "test.md", heading: str = "Section") -> Chunk:
    return Chunk(
        page_content=content,
        metadata={"source_file": source, "section_heading": heading},
    )


def mock_completion(text: str) -> MagicMock:
    """Build a minimal litellm completion response mock."""
    response = MagicMock()
    response.choices[0].message.content = text
    return response


# ---------------------------------------------------------------------------
# merge_chunks
# ---------------------------------------------------------------------------


def test_merge_chunks_deduplicates_by_page_content():
    a = make_chunk("shared content")
    b = make_chunk("unique to primary")
    c = make_chunk("shared content")  # duplicate of a
    d = make_chunk("unique to secondary")

    result = merge_chunks([a, b], [c, d])

    contents = [r.page_content for r in result]
    assert contents.count("shared content") == 1
    assert "unique to primary" in contents
    assert "unique to secondary" in contents


def test_merge_chunks_preserves_primary_order():
    chunks = [make_chunk(f"chunk {i}") for i in range(5)]
    result = merge_chunks(chunks, [])
    assert [r.page_content for r in result] == [c.page_content for c in chunks]


def test_merge_chunks_appends_novel_secondary_chunks():
    primary = [make_chunk("primary only")]
    secondary = [make_chunk("primary only"), make_chunk("secondary only")]

    result = merge_chunks(primary, secondary)

    assert len(result) == 2
    assert result[0].page_content == "primary only"
    assert result[1].page_content == "secondary only"


def test_merge_chunks_with_empty_secondary_returns_primary():
    primary = [make_chunk("a"), make_chunk("b")]
    result = merge_chunks(primary, [])
    assert result == primary


def test_merge_chunks_with_empty_primary_returns_all_secondary():
    secondary = [make_chunk("x"), make_chunk("y")]
    result = merge_chunks([], secondary)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _format_context
# ---------------------------------------------------------------------------


def test_format_context_labels_each_chunk_with_source_and_heading():
    chunks = [
        make_chunk("AI skills content", source="skills.md", heading="AI Stack"),
        make_chunk("Experience content", source="experience.md", heading="PhD Role"),
    ]
    context = _format_context(chunks)

    assert "skills.md" in context
    assert "AI Stack" in context
    assert "experience.md" in context
    assert "PhD Role" in context


def test_format_context_includes_page_content():
    chunk = make_chunk("The actual text of the chunk.")
    context = _format_context([chunk])
    assert "The actual text of the chunk." in context


def test_format_context_separates_chunks():
    chunks = [make_chunk(f"content {i}") for i in range(3)]
    context = _format_context(chunks)
    # Each chunk should be findable, and there should be separators between them
    for i in range(3):
        assert f"content {i}" in context
    assert "---" in context


def test_format_context_handles_missing_metadata_gracefully():
    chunk = Chunk(page_content="bare content", metadata={})
    context = _format_context([chunk])
    # Should not raise — falls back to '?' for missing keys
    assert "bare content" in context
    assert "?" in context


# ---------------------------------------------------------------------------
# make_rag_messages
# ---------------------------------------------------------------------------


def test_make_rag_messages_structure():
    chunks = [make_chunk("some context")]
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    messages = make_rag_messages("current question", history, chunks)

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "previous question"
    assert messages[2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "current question"


def test_make_rag_messages_context_appears_in_system_prompt():
    chunks = [make_chunk("Alejandro's PhD was at James Cook University.")]
    messages = make_rag_messages("Where did he study?", [], chunks)

    system_content = messages[0]["content"]
    assert "James Cook University" in system_content


def test_make_rag_messages_with_no_history():
    chunks = [make_chunk("context")]
    messages = make_rag_messages("question", [], chunks)

    assert len(messages) == 2  # system + user
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# rerank — guard logic
# ---------------------------------------------------------------------------


def test_rerank_reorders_chunks_by_returned_ids():
    chunks = [make_chunk(f"chunk {i}") for i in range(3)]
    # LLM returns [3, 1, 2] — third chunk first
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[3, 1, 2]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert result[0].page_content == "chunk 2"
    assert result[1].page_content == "chunk 0"
    assert result[2].page_content == "chunk 1"


def test_rerank_guard_drops_out_of_range_ids():
    chunks = [make_chunk(f"chunk {i}") for i in range(3)]
    # LLM returns an out-of-range ID (99) alongside valid ones
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[99, 1, 2, 3]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert len(result) == 3
    assert all(c.page_content.startswith("chunk") for c in result)


def test_rerank_guard_deduplicates_repeated_ids():
    chunks = [make_chunk(f"chunk {i}") for i in range(3)]
    # LLM returns chunk 1 twice
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[1, 1, 2, 3]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert len(result) == 3
    contents = [r.page_content for r in result]
    assert contents.count("chunk 0") == 1


def test_rerank_guard_appends_chunks_omitted_by_model():
    chunks = [make_chunk(f"chunk {i}") for i in range(4)]
    # LLM only returns 3 of 4 IDs — chunk 3 is missing
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[4, 1, 2]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert len(result) == 4
    # chunk 2 (ID 3) should be appended at the end
    assert result[-1].page_content == "chunk 2"


# ---------------------------------------------------------------------------
# rewrite_query — history threading
# ---------------------------------------------------------------------------


def test_rewrite_query_includes_question_in_prompt():
    with patch("answer.completion", return_value=mock_completion("rewritten query")) as mock_call:
        rewrite_query("What Bayesian methods has Alejandro used?")

    prompt = mock_call.call_args[1]["messages"][0]["content"]
    assert "What Bayesian methods has Alejandro used?" in prompt


def test_rewrite_query_includes_history_in_prompt():
    history = [
        {"role": "user", "content": "Tell me about his PhD"},
        {"role": "assistant", "content": "He did his PhD at JCU"},
    ]
    with patch("answer.completion", return_value=mock_completion("refined query")) as mock_call:
        rewrite_query("What were the main findings?", history)

    prompt = mock_call.call_args[1]["messages"][0]["content"]
    assert "Tell me about his PhD" in prompt
    assert "He did his PhD at JCU" in prompt


def test_rewrite_query_returns_model_output():
    with patch("answer.completion", return_value=mock_completion("  Bayesian ecology methods  ")):
        result = rewrite_query("question")

    assert result == "Bayesian ecology methods"  # stripped


# ---------------------------------------------------------------------------
# fetch_context_unranked — DB wiring
# ---------------------------------------------------------------------------


def test_fetch_context_unranked_constructs_chunks_from_db_results():
    fake_results = {
        "documents": [["doc content A", "doc content B"]],
        "metadatas": [
            [{"source_file": "a.md", "section_heading": "A"},
             {"source_file": "b.md", "section_heading": "B"}]
        ],
    }
    with (
        patch("answer._embed", return_value=[0.0] * 3072),
        patch("answer.collection.query", return_value=fake_results),
    ):
        chunks = fetch_context_unranked("any question")

    assert len(chunks) == 2
    assert chunks[0].page_content == "doc content A"
    assert chunks[0].metadata["source_file"] == "a.md"
    assert chunks[1].page_content == "doc content B"
    assert chunks[1].metadata["section_heading"] == "B"


# ---------------------------------------------------------------------------
# answer_question — end-to-end pipeline
# ---------------------------------------------------------------------------


def test_answer_question_returns_answer_and_chunks():
    chunks = [make_chunk("relevant context", "skills.md", "AI Stack")]

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("Here is the answer.")),
    ):
        answer, returned_chunks = answer_question("What skills does Alejandro have?")

    assert isinstance(answer, str)
    assert len(answer) > 0
    assert returned_chunks == chunks


def test_answer_question_threads_history_into_messages():
    history = [{"role": "user", "content": "previous"}, {"role": "assistant", "content": "reply"}]
    chunks = [make_chunk("context")]

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")) as mock_call,
    ):
        answer_question("follow-up question", history)

    messages = mock_call.call_args[1]["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]


def test_answer_question_limits_context_to_final_k():
    # fetch_context should return at most FINAL_K chunks — verify pipeline respects the limit
    many_chunks = [make_chunk(f"chunk {i}") for i in range(FINAL_K + 5)]

    with (
        patch("answer.fetch_context", return_value=many_chunks[:FINAL_K]),
        patch("answer.completion", return_value=mock_completion("answer")),
    ):
        _, returned_chunks = answer_question("question")

    assert len(returned_chunks) <= FINAL_K


# ---------------------------------------------------------------------------
# _rerun — feedback injection
# ---------------------------------------------------------------------------


def test_rerun_appends_previous_answer_to_system_prompt():
    chunks = [make_chunk("context")]
    with patch("answer.completion", return_value=mock_completion("revised answer")) as mock_call:
        _rerun("question", [], chunks, "bad answer", "Answer was off-topic.")

    system_content = mock_call.call_args[1]["messages"][0]["content"]
    assert "bad answer" in system_content


def test_rerun_appends_feedback_to_system_prompt():
    chunks = [make_chunk("context")]
    with patch("answer.completion", return_value=mock_completion("revised answer")) as mock_call:
        _rerun("question", [], chunks, "bad answer", "Answer was off-topic.")

    system_content = mock_call.call_args[1]["messages"][0]["content"]
    assert "Answer was off-topic." in system_content


def test_rerun_threads_history_into_messages():
    history = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "reply"}]
    chunks = [make_chunk("context")]
    with patch("answer.completion", return_value=mock_completion("revised")) as mock_call:
        _rerun("question", history, chunks, "bad answer", "feedback")

    messages = mock_call.call_args[1]["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]


def test_rerun_returns_new_answer_string():
    chunks = [make_chunk("context")]
    with patch("answer.completion", return_value=mock_completion("revised answer")):
        result = _rerun("question", [], chunks, "old answer", "feedback")

    assert result == "revised answer"


# ---------------------------------------------------------------------------
# answer_with_guardrail — retry loop
# ---------------------------------------------------------------------------


def make_evaluation(is_acceptable: bool, feedback: str = ""):
    from guardrail import Evaluation
    return Evaluation(is_acceptable=is_acceptable, feedback=feedback)


def test_answer_with_guardrail_returns_on_first_acceptable_answer():
    chunks = [make_chunk("context")]
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("good answer")),
        patch("answer.evaluate", return_value=make_evaluation(True)),
    ):
        answer, returned_chunks = answer_with_guardrail("question")

    assert answer == "good answer"
    assert returned_chunks == chunks


def test_answer_with_guardrail_retries_on_rejection():
    chunks = [make_chunk("context")]
    evaluate_calls = []

    def fake_evaluate(*args, **kwargs):
        evaluate_calls.append(1)
        # Reject first call, accept second
        return make_evaluation(len(evaluate_calls) > 1)

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")),
        patch("answer.evaluate", side_effect=fake_evaluate),
    ):
        answer, _ = answer_with_guardrail("question")

    assert len(evaluate_calls) == 2


def test_answer_with_guardrail_returns_canned_refusal_after_max_retries():
    chunks = [make_chunk("context")]
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("bad answer")),
        patch("answer.evaluate", return_value=make_evaluation(False, "still wrong")),
    ):
        answer, _ = answer_with_guardrail("question")

    assert answer == CANNED_REFUSAL


def test_answer_with_guardrail_evaluates_at_most_max_retries_plus_one_times():
    chunks = [make_chunk("context")]
    evaluate_calls = []

    def fake_evaluate(*args, **kwargs):
        evaluate_calls.append(1)
        return make_evaluation(False, "rejected")

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")),
        patch("answer.evaluate", side_effect=fake_evaluate),
    ):
        answer_with_guardrail("question")

    assert len(evaluate_calls) == MAX_RETRIES + 1

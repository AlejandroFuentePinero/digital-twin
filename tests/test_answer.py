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
    MAX_ATTEMPTS,
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
    """merge_chunks deduplicates so the LLM never sees the same content twice."""
    a = make_chunk("shared content")
    b = make_chunk("unique to primary")
    c = make_chunk("shared content")
    d = make_chunk("unique to secondary")

    result = merge_chunks([a, b], [c, d])

    contents = [r.page_content for r in result]
    assert contents.count("shared content") == 1
    assert "unique to primary" in contents
    assert "unique to secondary" in contents


def test_merge_chunks_preserves_primary_order():
    """Primary chunks keep their relative order — rerank ordering is preserved."""
    chunks = [make_chunk(f"chunk {i}") for i in range(5)]
    result = merge_chunks(chunks, [])
    assert [r.page_content for r in result] == [c.page_content for c in chunks]


def test_merge_chunks_appends_novel_secondary_chunks():
    """Novel secondary chunks are appended after the primary list."""
    primary = [make_chunk("primary only")]
    secondary = [make_chunk("primary only"), make_chunk("secondary only")]

    result = merge_chunks(primary, secondary)

    assert len(result) == 2
    assert result[0].page_content == "primary only"
    assert result[1].page_content == "secondary only"


def test_merge_chunks_with_empty_secondary_returns_primary():
    """An empty secondary list leaves the primary list unchanged."""
    primary = [make_chunk("a"), make_chunk("b")]
    result = merge_chunks(primary, [])
    assert result == primary


def test_merge_chunks_with_empty_primary_returns_all_secondary():
    """An empty primary list lets every secondary chunk through."""
    secondary = [make_chunk("x"), make_chunk("y")]
    result = merge_chunks([], secondary)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _format_context
# ---------------------------------------------------------------------------


def test_format_context_labels_each_chunk_with_source_and_heading():
    """_format_context labels every chunk with its source file and section heading."""
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
    """_format_context includes each chunk's actual text, not just metadata."""
    chunk = make_chunk("The actual text of the chunk.")
    context = _format_context([chunk])
    assert "The actual text of the chunk." in context


def test_format_context_separates_chunks():
    """_format_context inserts a separator between chunks so the LLM can tell them apart."""
    chunks = [make_chunk(f"content {i}") for i in range(3)]
    context = _format_context(chunks)
    for i in range(3):
        assert f"content {i}" in context
    assert "---" in context


def test_format_context_handles_missing_metadata_gracefully():
    """_format_context falls back to '?' for missing metadata rather than raising."""
    chunk = Chunk(page_content="bare content", metadata={})
    context = _format_context([chunk])
    assert "bare content" in context
    assert "?" in context


# ---------------------------------------------------------------------------
# make_rag_messages
# ---------------------------------------------------------------------------


def test_make_rag_messages_structure():
    """make_rag_messages produces system → history turns → current question, in order."""
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    messages = make_rag_messages("current question", history, "some context")

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "previous question"
    assert messages[2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "current question"


def test_make_rag_messages_context_appears_in_system_prompt():
    """Retrieval context is embedded in the system prompt, not the user turn."""
    messages = make_rag_messages("Where did he study?", [], "Alejandro's PhD was at James Cook University.")

    system_content = messages[0]["content"]
    assert "James Cook University" in system_content


def test_make_rag_messages_with_no_history():
    """With no history, make_rag_messages emits just system + user."""
    messages = make_rag_messages("question", [], "context")

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# rerank — guard logic
# ---------------------------------------------------------------------------


def test_rerank_reorders_chunks_by_returned_ids():
    """rerank reorders chunks to match the order the model returned."""
    chunks = [make_chunk(f"chunk {i}") for i in range(3)]
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[3, 1, 2]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert result[0].page_content == "chunk 2"
    assert result[1].page_content == "chunk 0"
    assert result[2].page_content == "chunk 1"


def test_rerank_guard_drops_out_of_range_ids():
    """rerank silently drops chunk IDs the model invented."""
    chunks = [make_chunk(f"chunk {i}") for i in range(3)]
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[99, 1, 2, 3]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert len(result) == 3
    assert all(c.page_content.startswith("chunk") for c in result)


def test_rerank_guard_deduplicates_repeated_ids():
    """rerank deduplicates IDs the model emitted twice."""
    chunks = [make_chunk(f"chunk {i}") for i in range(3)]
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[1, 1, 2, 3]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert len(result) == 3
    contents = [r.page_content for r in result]
    assert contents.count("chunk 0") == 1


def test_rerank_guard_appends_chunks_omitted_by_model():
    """rerank appends any chunk the model forgot, so no chunk is silently dropped."""
    chunks = [make_chunk(f"chunk {i}") for i in range(4)]
    with patch("answer.completion", return_value=mock_completion(
        RankOrder(order=[4, 1, 2]).model_dump_json()
    )):
        result = rerank("question", chunks)

    assert len(result) == 4
    assert result[-1].page_content == "chunk 2"


# ---------------------------------------------------------------------------
# rewrite_query — history threading
# ---------------------------------------------------------------------------


def test_rewrite_query_includes_question_in_prompt():
    """rewrite_query passes the user's question into the rewrite prompt."""
    with patch("answer.completion", return_value=mock_completion("rewritten query")) as mock_call:
        rewrite_query("What Bayesian methods has Alejandro used?")

    prompt = mock_call.call_args[1]["messages"][0]["content"]
    assert "What Bayesian methods has Alejandro used?" in prompt


def test_rewrite_query_includes_history_in_prompt():
    """rewrite_query includes prior turns so follow-up references can be resolved."""
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
    """rewrite_query returns the model output stripped of surrounding whitespace."""
    with patch("answer.completion", return_value=mock_completion("  Bayesian ecology methods  ")):
        result = rewrite_query("question")

    assert result == "Bayesian ecology methods"


# ---------------------------------------------------------------------------
# fetch_context_unranked — DB wiring
# ---------------------------------------------------------------------------


def test_fetch_context_unranked_constructs_chunks_from_db_results():
    """fetch_context_unranked converts ChromaDB rows into Chunk objects with metadata."""
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
    """answer_question returns both the generated answer and the chunks used."""
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
    """answer_question threads prior conversation turns into the LLM messages."""
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
    """answer_question never feeds more than FINAL_K chunks to the LLM."""
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
    """_rerun shows the rejected answer to the model so it can revise rather than restart."""
    with patch("answer.completion", return_value=mock_completion("revised answer")) as mock_call:
        _rerun("question", [], "context text", "bad answer", "Answer was off-topic.")

    system_content = mock_call.call_args[1]["messages"][0]["content"]
    assert "bad answer" in system_content


def test_rerun_appends_feedback_to_system_prompt():
    """_rerun injects guardrail feedback into the system prompt to steer the revision."""
    with patch("answer.completion", return_value=mock_completion("revised answer")) as mock_call:
        _rerun("question", [], "context text", "bad answer", "Answer was off-topic.")

    system_content = mock_call.call_args[1]["messages"][0]["content"]
    assert "Answer was off-topic." in system_content


def test_rerun_threads_history_into_messages():
    """_rerun preserves prior conversation turns when retrying a rejected answer."""
    history = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "reply"}]
    with patch("answer.completion", return_value=mock_completion("revised")) as mock_call:
        _rerun("question", history, "context text", "bad answer", "feedback")

    messages = mock_call.call_args[1]["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]


def test_rerun_returns_new_answer_string():
    """_rerun returns the model's revised answer as a plain string."""
    with patch("answer.completion", return_value=mock_completion("revised answer")):
        result = _rerun("question", [], "context text", "old answer", "feedback")

    assert result == "revised answer"


# ---------------------------------------------------------------------------
# answer_with_guardrail — retry loop
# ---------------------------------------------------------------------------


def make_evaluation(is_acceptable: bool, feedback: str = ""):
    from guardrail import Evaluation
    return Evaluation(is_acceptable=is_acceptable, feedback=feedback)


def test_answer_with_guardrail_returns_on_first_acceptable_answer():
    """answer_with_guardrail short-circuits as soon as the guardrail accepts."""
    chunks = [make_chunk("context")]
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("good answer")),
        patch("answer.evaluate", return_value=make_evaluation(True)),
        patch("answer.log_interaction"),
    ):
        answer, returned_chunks = answer_with_guardrail("question")

    assert answer == "good answer"
    assert returned_chunks == chunks


def test_answer_with_guardrail_retries_on_rejection():
    """answer_with_guardrail retries when the guardrail rejects the first answer."""
    chunks = [make_chunk("context")]
    evaluate_calls = []

    def fake_evaluate(*args, **kwargs):
        evaluate_calls.append(1)
        return make_evaluation(len(evaluate_calls) > 1)

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")),
        patch("answer.evaluate", side_effect=fake_evaluate),
        patch("answer.log_interaction"),
    ):
        answer, _ = answer_with_guardrail("question")

    assert len(evaluate_calls) == 2


def test_answer_with_guardrail_returns_canned_refusal_after_max_retries():
    """After MAX_ATTEMPTS rejections, answer_with_guardrail returns the canned refusal."""
    chunks = [make_chunk("context")]
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("bad answer")),
        patch("answer.evaluate", return_value=make_evaluation(False, "still wrong")),
        patch("answer.log_interaction"),
    ):
        answer, _ = answer_with_guardrail("question")

    assert answer == CANNED_REFUSAL


def test_answer_with_guardrail_evaluates_at_most_max_attempts_times():
    """The guardrail retry loop is capped at MAX_ATTEMPTS evaluations."""
    chunks = [make_chunk("context")]
    evaluate_calls = []

    def fake_evaluate(*args, **kwargs):
        evaluate_calls.append(1)
        return make_evaluation(False, "rejected")

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")),
        patch("answer.evaluate", side_effect=fake_evaluate),
        patch("answer.log_interaction"),
    ):
        answer_with_guardrail("question")

    assert len(evaluate_calls) == MAX_ATTEMPTS


def test_answer_with_guardrail_logs_once_per_call():
    """Each answer_with_guardrail call writes exactly one interaction log entry."""
    chunks = [make_chunk("context")]
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("good answer")),
        patch("answer.evaluate", return_value=make_evaluation(True)),
        patch("answer.log_interaction") as mock_log,
    ):
        answer_with_guardrail("question")

    assert mock_log.call_count == 1


def test_answer_with_guardrail_logs_retry_count():
    """The logged retry_count reflects how many times the guardrail rejected."""
    chunks = [make_chunk("context")]
    evaluate_calls = []

    def fake_evaluate(*args, **kwargs):
        evaluate_calls.append(1)
        return make_evaluation(len(evaluate_calls) > 1)

    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")),
        patch("answer.evaluate", side_effect=fake_evaluate),
        patch("answer.log_interaction") as mock_log,
    ):
        answer_with_guardrail("question")

    _, _, _, _, retry_count, _ = mock_log.call_args[0]
    assert retry_count == 1


def test_answer_with_guardrail_logs_knew_answer_false_for_gap_phrase():
    """Gap-phrase answers are logged with knew_answer=False so KB gaps are visible."""
    chunks = [make_chunk("context")]
    gap_answer = "I don't have that information in my knowledge base."
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion(gap_answer)),
        patch("answer.evaluate", return_value=make_evaluation(True)),
        patch("answer.log_interaction") as mock_log,
    ):
        answer_with_guardrail("question")

    _, _, _, knew_answer, _, _ = mock_log.call_args[0]
    assert knew_answer is False


def test_answer_with_guardrail_passes_session_id_to_log():
    """answer_with_guardrail forwards session_id to the interaction logger."""
    chunks = [make_chunk("context")]
    with (
        patch("answer.fetch_context", return_value=chunks),
        patch("answer.completion", return_value=mock_completion("answer")),
        patch("answer.evaluate", return_value=make_evaluation(True)),
        patch("answer.log_interaction") as mock_log,
    ):
        answer_with_guardrail("question", session_id="test-session")

    _, _, _, _, _, session_id = mock_log.call_args[0]
    assert session_id == "test-session"

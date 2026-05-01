from types import SimpleNamespace
from unittest.mock import patch

from retrieval import Chunk, fetch_context, format_context, merge_chunks, rerank


def test_merge_chunks_deduplicates_so_the_llm_never_sees_the_same_content_twice():
    """merge_chunks drops secondary entries whose page_content already appears in primary."""
    primary = [
        Chunk(page_content="a", metadata={}),
        Chunk(page_content="b", metadata={}),
    ]
    secondary = [
        Chunk(page_content="b", metadata={}),  # duplicate
        Chunk(page_content="c", metadata={}),
    ]
    merged = merge_chunks(primary, secondary)
    contents = [c.page_content for c in merged]
    assert contents == ["a", "b", "c"]


def test_format_context_labels_each_chunk_with_source_file_and_section_heading():
    """format_context emits a `[source_file — section_heading]` label above each chunk body."""
    chunks = [
        Chunk(
            page_content="Body of chunk 1.",
            metadata={"source_file": "publications.md", "section_heading": "Iriarte 2021"},
        ),
        Chunk(
            page_content="Body of chunk 2.",
            metadata={"source_file": "experience.md", "section_heading": "Bolivia"},
        ),
    ]
    out = format_context(chunks)
    assert "[publications.md — Iriarte 2021]" in out
    assert "Body of chunk 1." in out
    assert "[experience.md — Bolivia]" in out
    assert "Body of chunk 2." in out


def _completion_returning_json(payload: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


def test_rerank_returns_chunks_in_the_order_requested_by_the_model():
    """rerank reorders the input chunks per the LLM's RankOrder JSON response."""
    chunks = [
        Chunk(page_content="alpha", metadata={}),
        Chunk(page_content="beta", metadata={}),
        Chunk(page_content="gamma", metadata={}),
    ]
    # Model says: chunk 3 most relevant, then 1, then 2.
    payload = '{"order": [3, 1, 2]}'
    with patch("retrieval.completion", return_value=_completion_returning_json(payload)):
        out = rerank("any question", chunks)
    assert [c.page_content for c in out] == ["gamma", "alpha", "beta"]


def test_fetch_context_runs_rewrite_then_dual_query_then_rerank():
    """fetch_context calls rewrite_query, fetches against both original and rewritten, merges, and reranks."""
    primary = [Chunk(page_content="orig-hit", metadata={})]
    secondary = [Chunk(page_content="rewritten-hit", metadata={})]

    with patch("retrieval.rewrite_query", return_value="rewritten-q") as mock_rewrite, \
         patch("retrieval.fetch_context_unranked", side_effect=[primary, secondary]) as mock_fetch, \
         patch("retrieval.rerank", side_effect=lambda q, chunks: chunks) as mock_rerank:
        out = fetch_context("orig-q", history=[])

    mock_rewrite.assert_called_once_with("orig-q", [])
    # Two unranked queries — one with the original, one with the rewritten
    assert mock_fetch.call_count == 2
    fetched_questions = [c.args[0] for c in mock_fetch.call_args_list]
    assert "orig-q" in fetched_questions
    assert "rewritten-q" in fetched_questions
    mock_rerank.assert_called_once()
    # Merged + reranked output preserves both sources, deduped
    contents = [c.page_content for c in out]
    assert "orig-hit" in contents
    assert "rewritten-hit" in contents

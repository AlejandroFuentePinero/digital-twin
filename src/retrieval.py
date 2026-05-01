"""Retrieval helpers — embedding, ChromaDB query, merge, rewrite, rerank, format.

Extracted from the pre-redesign `answer.py` (issue #13 step 6). Surface unchanged
from the original implementation; the only renames are `_format_context` →
`format_context` (now public).
"""

from pathlib import Path

from chromadb import PersistentClient
from dotenv import load_dotenv
from litellm import completion
from openai import OpenAI
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv(override=True)

DB_PATH = str(Path(__file__).parent.parent / "data" / "preprocessed_db")
COLLECTION = "digital_twin"
EMBED_MODEL = "text-embedding-3-large"
MODEL = "openai/gpt-4.1"
REWRITE_MODEL = "openai/gpt-4.1-nano"
RETRIEVAL_K = 20
FINAL_K = 10

_wait = wait_exponential(multiplier=1, min=10, max=120)
_stop = stop_after_attempt(5)

_openai_client = OpenAI()
_chroma = PersistentClient(path=DB_PATH)
collection = _chroma.get_or_create_collection(COLLECTION)


class Chunk(BaseModel):
    page_content: str
    metadata: dict


class RankOrder(BaseModel):
    order: list[int] = Field(
        description="Chunk IDs ordered from most to least relevant"
    )


def _embed(text: str) -> list[float]:
    return (
        _openai_client.embeddings.create(model=EMBED_MODEL, input=[text])
        .data[0]
        .embedding
    )


def fetch_context_unranked(question: str) -> list[Chunk]:
    results = collection.query(
        query_embeddings=[_embed(question)], n_results=RETRIEVAL_K
    )
    return [
        Chunk(page_content=doc, metadata=meta)
        for doc, meta in zip(results["documents"][0], results["metadatas"][0])
    ]


def merge_chunks(primary: list[Chunk], secondary: list[Chunk]) -> list[Chunk]:
    seen = {c.page_content for c in primary}
    return primary + [c for c in secondary if c.page_content not in seen]


@retry(wait=_wait, stop=_stop)
def rewrite_query(question: str, history: list[dict] | None = None) -> str:
    """Rewrite the user's question as a short, search-optimised KB query."""
    history_text = ""
    if history:
        for msg in history[-4:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"

    prompt = f"""\
You are preparing a search query for a knowledge base about Alejandro de la Fuente's \
professional background (AI engineer, data scientist, quantitative ecologist).

Recent conversation:
{history_text or "(none)"}

User's question: {question}

Write a short, precise search query (under 15 words) that will surface the most relevant \
content from the knowledge base. Focus on specific skills, projects, roles, or topics named \
in the question. Respond with the query only — no explanation, no punctuation at the end."""

    response = completion(
        model=REWRITE_MODEL, messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()


@retry(wait=_wait, stop=_stop)
def rerank(question: str, chunks: list[Chunk]) -> list[Chunk]:
    """Reorder chunks by relevance to the original question."""
    system = (
        "You are a document re-ranker. Given a question and a numbered list of text chunks, "
        "return the chunk IDs reordered from most to least relevant to the question. "
        "Include every chunk ID exactly once."
    )
    chunk_text = "\n\n".join(
        f"# CHUNK {i + 1}:\n{c.page_content}" for i, c in enumerate(chunks)
    )
    user = (
        f"Question: {question}\n\n{chunk_text}\n\n"
        "Reply with the reranked chunk IDs only."
    )
    response = completion(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=RankOrder,
    )
    order = RankOrder.model_validate_json(response.choices[0].message.content).order
    seen = set()
    safe_order: list[int] = []
    for i in order:
        if 1 <= i <= len(chunks) and i not in seen:
            safe_order.append(i)
            seen.add(i)
    for i in range(1, len(chunks) + 1):
        if i not in seen:
            safe_order.append(i)
    return [chunks[i - 1] for i in safe_order]


def fetch_context(
    question: str, history: list[dict] | None = None
) -> list[Chunk]:
    rewritten = rewrite_query(question, history)
    primary = fetch_context_unranked(question)
    secondary = fetch_context_unranked(rewritten)
    merged = merge_chunks(primary, secondary)
    reranked = rerank(question, merged)
    return reranked[:FINAL_K]


def format_context(chunks: list[Chunk]) -> str:
    parts = []
    for chunk in chunks:
        label = (
            f"[{chunk.metadata.get('source_file', '?')} — "
            f"{chunk.metadata.get('section_heading', '?')}]"
        )
        parts.append(f"{label}\n{chunk.page_content}")
    return "\n\n---\n\n".join(parts)

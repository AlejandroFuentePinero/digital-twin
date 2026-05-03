# Expert Knowledge Worker (RAG Chatbot)

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/RAG_expert_knowledge_worker

## What it is

A RAG assistant for answering questions about a company knowledge base (Insurellm). Two complete pipelines (a LangChain baseline and a from-scratch optimised pipeline), a Gradio chat UI that shows both the answer and the retrieved source context side-by-side for transparency, and a standalone evaluation dashboard measuring retrieval and answer quality against a labelled test set.

The most technically sophisticated supporting project in the LLM Engineering Lab — directly validates the RAG evaluation pattern Alejandro applies in his own projects (including this Digital Twin). The hierarchical RAG design, query rewriting, and LLM reranking are the same patterns described in the Digital Twin architecture.

## Architecture

Two interchangeable pipelines, swappable with a one-line import change.

### Baseline pipeline (LangChain + ChromaDB)

- **Document ingestion** (`src/implementation/ingest.py`) — loads Markdown grouped by subfolder, tags with metadata (`doc_type`), splits with recursive text splitter (`chunk_size=500`, `chunk_overlap=200`), persists to Chroma collection.
- **Retrieval** — k=10, conversation-aware (current question + prior user turns to handle ellipsis follow-ups like "what about pricing?").
- **Answering** — retrieved context injected into system prompt; chat model generates grounded response.
- **UI** — chat interface + side panel showing retrieved chunks with source metadata for trust assessment.

### Optimised pipeline (`optimised_ingest.py` + `optimised_answer.py`)

Drop-in replacement removing LangChain abstractions; uses OpenAI SDK + ChromaDB + LiteLLM directly.

- **LLM-based chunking instead of fixed-size splits.** An LLM reads each document and returns chunks as structured objects with three fields: `headline` (optimised to match likely query phrasing), `summary` (synthesises what the chunk answers), `original_text` (verbatim source). All three concatenated and embedded together — each vector encodes both dense original content AND LLM-generated surface forms most likely to be retrieved. Documents processed in parallel via `multiprocessing.Pool`.
- **Hierarchical RAG.** For each subfolder, an LLM aggregates all documents into a `summary_{category}.md` saved to `knowledge-base/summaries/`. Designed to answer holistic questions (totals, counts, averages, rankings) hard to answer from individual fine-grained chunks. Summaries stored as single unsplit documents in the same Chroma collection — surface automatically via semantic search; reranker promotes for holistic queries, demotes for specific lookups. No retrieval-pipeline changes needed.
- **Four-stage answering** (vs. baseline's single vector lookup):
  1. **Query rewriting** — rewrite user question into tighter KB query, stripping conversational noise.
  2. **Dual retrieval pass** — original question + rewritten query each return `RETRIEVAL_K = 20` chunks.
  3. **Chunk merging** — dedupe into single pool.
  4. **LLM reranking** — dedicated reranker call returns `RankOrder` structured output; top `FINAL_K = 10` passed to answer model.
- **`tenacity` retry logic** wraps all LLM calls for rate-limit graceful degradation.

## Key engineering decisions

- **Three-field chunk encoding (headline + summary + original).** Standard approach embeds the raw text only. Encoding LLM-generated surface forms alongside the source dramatically improves retrieval recall for queries that don't match the source text's exact phrasing — common for downstream-question shapes.
- **Hierarchical RAG via category summaries in the same collection.** No separate "summary index" or routing logic — summaries live alongside chunks; the reranker handles selection. Cleanest architecture for holistic+specific question mix.
- **Visible retrieved context in the UI.** Trust + debugging: users see *what the model answered from*, which is faster than reading the answer alone for verification. Becomes a standard pattern Alejandro carries forward.
- **Same `app.py` works for either pipeline.** One-line import swap (`from src.implementation.answer ...` → `from src.implementation.optimised_answer ...`). Baseline and optimised are kept as parallel implementations for benchmarking and pedagogical clarity.

## Evaluation

Standalone evaluation suite (`evaluator.py` + `src/evaluation/`) measures retrieval and answer quality against a labelled test set (`tests.jsonl`).

**Retrieval metrics** per question:
- **MRR** (Mean Reciprocal Rank) — rank of first chunk containing each expected keyword.
- **nDCG** (Normalized Discounted Cumulative Gain) — position-weighted keyword coverage across the result list.
- **Keyword coverage** — fraction of expected keywords found anywhere in retrieved results.

**Answer quality** via LLM-as-judge (`gpt-4.1-nano`), 1–5 scale on:
- **Accuracy** — factual correctness vs reference.
- **Completeness** — coverage of key reference information.
- **Relevance** — directly addresses the question without unnecessary additions.

Results displayed in a Gradio dashboard with colour-coded metrics (green/amber/red) and per-category bar charts. CLI mode (`eval.py <test_row_number>`) for single-test inspection.

## Stack

Python · OpenAI SDK · LangChain (baseline) · ChromaDB · LiteLLM · Gradio · `tenacity` · Pydantic · `text-embedding-3-large`

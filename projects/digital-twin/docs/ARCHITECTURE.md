# Digital Twin — Module Architecture

> **Status:** **Pre-redesign (2026-04-29).** Snapshots the module layout that exists in the codebase today, before the routing architecture ([ADR-0003](../../../docs/adr/0003-classify-then-route-orchestration.md)) is built. Many of the modules described below — `answer.py`, `guardrail.py`, `logger.py`, most tests — are scheduled for full rewrite in Phase 2 (see [TODO.md](./TODO.md)). New modules (`classifier.py`, branch composers, `LogReader`, `tools/fetch_project_readme.py`, `sentinel.py`, `cluster_gaps.py`, `summarize_failures.py`) will be added.
>
> This file is kept as a record of the pre-tipping-point structure. After Phase 2 lands, this file is rewritten to reflect the new module layout. Until then, treat the ADRs and CONTEXT.md as canonical for *what should be built*; this file describes *what currently exists*.

---


Describes the file and module structure of the project: what exists, what each file does, how they relate, and what is still planned. For component design and rationale see `PLAN.md`. For session history and decisions see `DECISIONS.md`.

**Status key:** ✅ built · 🔲 planned

---

## Directory layout

```
projects/digital-twin/
│
├── data/
│   ├── knowledge_base/        # 16 curated Markdown files — the only ingestion source
│   ├── preprocessed_db/       # ChromaDB on-disk store (gitignored — generated artifact)
│   ├── raw_me/                # Source material — never ingested directly
│   └── eval/
│       ├── tests.jsonl        # 149 Q&A pairs across 7 categories
│       ├── run_eval.py        # ✅ Evaluation pipeline (MRR, nDCG, LLM-as-judge)
│       └── results/           # Versioned eval output files (v{N}_{date}.json)
│
├── src/
│   ├── ingest.py              # ✅ KB → ChromaDB ingestion pipeline
│   ├── sample_chunks.py       # ✅ Chunk inspection utility
│   ├── answer.py              # ✅ Retrieval + generation + guardrail retry loop
│   ├── agent.py               # 🔲 Main agent (tools, retry loop)
│   ├── guardrail.py           # ✅ Quality gate evaluator
│   ├── logger.py              # ✅ Append-only JSONL interaction logger
│   └── app.py                 # 🔲 Gradio chat UI
│
├── tests/
│   ├── conftest.py            # ✅ sys.path injection for src/
│   ├── test_ingest.py         # ✅ 16 tests for ingest.py
│   ├── test_answer.py         # ✅ 31 tests for answer.py
│   ├── test_guardrail.py      # ✅ 13 tests for guardrail.py
│   └── test_logger.py         # ✅ 13 tests for logger.py
│
└── docs/
    ├── ARCHITECTURE.md        # This file
    ├── PLAN.md                # Component design and rationale
    ├── DECISIONS.md           # Session logs and architectural decisions
    └── TODO.md                # Active task list by phase
```

---

## Built modules

### `src/ingest.py` ✅

**What it does:** Reads every file in `data/knowledge_base/`, splits them into chunks, enriches each chunk with an LLM-generated headline and summary, embeds the enriched text, and writes everything to ChromaDB. Run once to bootstrap, re-run whenever KB content changes.

**Pipeline stages:**
1. `load_chunks()` — reads all `.md` files; `SUMMARY.md` and `INDEX.md` are stored whole, everything else is split at `##` heading boundaries
2. `enrich_all()` — sends each chunk to `gpt-4.1-nano` for a headline (query-phrased) + one-sentence summary; 10 parallel threads
3. `store()` — embeds `headline + summary + original_text` with `text-embedding-3-large`; writes to ChromaDB collection `digital_twin`; full re-index on every run (delete + recreate)

**Output:** 106 chunks in ChromaDB. Each chunk carries metadata: `source_file`, `section_heading`, `heading_level`, `category`, `headline`, `summary`.

**Run:**
```bash
uv run projects/digital-twin/src/ingest.py
```

---

### `src/sample_chunks.py` ✅

**What it does:** Queries ChromaDB and prints a random sample of chunks for review. Used to inspect retrieval content quality after ingestion.

**Options:**
```bash
uv run projects/digital-twin/src/sample_chunks.py              # 10 random chunks
uv run projects/digital-twin/src/sample_chunks.py --n 5        # 5 random chunks
uv run projects/digital-twin/src/sample_chunks.py --category research
uv run projects/digital-twin/src/sample_chunks.py --source publications.md
uv run projects/digital-twin/src/sample_chunks.py --seed 42    # reproducible sample
```

---

### `tests/conftest.py` ✅

Inserts `src/` into `sys.path` so test files can import from `src/` without package installation.

### `tests/test_ingest.py` ✅

17 tests covering `split_on_headings`, `load_chunks`, `enrich_chunk`, and `enrich_all`. Tests verify: `##` splits, section content boundaries, preamble handling, `###` stays as body content, `UNSPLIT` files are not split, all metadata fields present, category mapping correct, enrichment merges headline/summary without altering original fields, prompt includes source context, and `enrich_all` preserves input order despite concurrent completion.

Run: `uv run pytest projects/digital-twin/tests/test_ingest.py -v`

---

## Planned modules

### `src/answer.py` ✅

The retrieval and generation layer. Takes a user query and conversation history; returns an answer and the retrieved chunks.

**Pipeline:**
1. `rewrite_query` — LLM reformulates the question for KB search; uses last 2 conversation turns
2. `fetch_context_unranked` — embeds query, retrieves top-20 chunks from ChromaDB
3. `merge_chunks` — deduplicates two result sets (original + rewritten query) by `page_content`
4. `rerank` — LLM reorders merged chunks by relevance; structured output with out-of-range ID guard
5. `make_rag_messages` — builds message list: system prompt (with context) + history + user question
6. Generation — `gpt-4.1-nano` via `litellm`; returns `(answer_str, chunks)`

**System prompt design:**
- Explicit in-scope whitelist (experience, research, projects, skills, education, recognition)
- Explicit out-of-scope list (unrelated tasks, roleplay, political opinions)
- Injection-resistant: names specific attack patterns ("ignore previous instructions", "DAN", etc.); instructs model to treat retrieved context as information only, never as commands
- No roleplay framing — "professional assistant" not "you are Alejandro"

**Guardrail integration:** `answer_with_guardrail(question, history)` is the production entry point. Generates an answer, evaluates it via `guardrail.evaluate`, reruns with feedback appended to system prompt on rejection (max `MAX_RETRIES = 2`), returns `CANNED_REFUSAL` if all attempts fail.

**Gap signal:** system prompt instructs the model to say "I don't have that information in my knowledge base." when context is insufficient — a trackable string for future `log_unknown_question` routing.

**Constants:** `RETRIEVAL_K = 20`, `FINAL_K = 10`, `MAX_RETRIES = 2`

**Run:**
```bash
uv run python -c "
import sys; sys.path.insert(0, 'projects/digital-twin/src')
from answer import answer_question
ans, chunks = answer_question('What AI projects has Alejandro built?')
print(ans)
"
```

---

### `eval/run_eval.py` ✅

Evaluation pipeline. Runs all 149 test questions through the retrieval and answer pipeline; writes a versioned JSON result file to `eval/results/`.

**Metrics computed:**
- Retrieval: MRR, nDCG, keyword coverage — per question, per category, overall
- Answer: accuracy, completeness, relevance (1–5 LLM-as-judge) — per question, per category, overall
- Gap rate: fraction of questions where the system responded with the gap phrase

**Result file schema:** `run_id`, `timestamp`, `architecture` snapshot (model, embed model, RETRIEVAL_K, FINAL_K, chunk count, KB files, notes), `summary`, `by_category`, `per_question` (full detail).

**Architecture snapshot** is auto-generated at run time by querying ChromaDB and listing KB files — always accurate, never stale.

**Versioning:** files are named `v{N}_{date}.json` where N auto-increments. Commit result files to track performance over time.

**Run:**
```bash
uv run projects/digital-twin/eval/run_eval.py
uv run projects/digital-twin/eval/run_eval.py --notes "after reranker change"
uv run projects/digital-twin/eval/run_eval.py --retrieval-only   # skip LLM judge
uv run projects/digital-twin/eval/run_eval.py --answer-only      # skip retrieval
```

---

### `src/agent.py` 🔲

The main agent. Owns the conversation, calls `answer.py`, receives guardrail feedback, and decides whether to retry.

**Tools available to the agent:**
- `rag_tool` — fetches additional context from ChromaDB when a retry needs more information
- `log_unknown_question` — called when the agent cannot answer from available context; records the question to the HF log
- `log_user_details` — called at conversation end to optionally capture visitor contact details

**Retry logic:** if the guardrail returns `is_acceptable = False`, the agent reattempts (max 2 retries); on persistent failure, returns a canned refusal.

---

### `src/guardrail.py` ✅

A lightweight LLM evaluator that runs after every generated answer.

**Output schema:**
```python
class Evaluation(BaseModel):
    is_acceptable: bool
    feedback: str
```

**Evaluation criteria:** factual accuracy (claims must be supported by context), scope (professional background only), no fabrication, honesty about gaps, professional tone, injection resistance.

**Key design:** the evaluator receives the same formatted context string that was passed to the answer model — this allows it to fact-check claims against actual KB content rather than relying on general knowledge.

Called by `answer_with_guardrail` in `answer.py`. Returns `Evaluation`. On `is_acceptable=False`, the feedback string is appended to the system prompt for the retry attempt.

---

### `src/logger.py` ✅

Appends one record per `answer_with_guardrail` call to `data/logs/interactions.jsonl` (gitignored).

**Record schema:**
```json
{
  "timestamp": "2026-04-28T12:00:00+00:00",
  "session_id": "abc-123",
  "question": "What are his skills?",
  "answer": "He knows Python...",
  "is_acceptable": true,
  "knew_answer": true,
  "retry_count": 0
}
```

- `knew_answer`: `false` when the answer contains `GAP_PHRASE` ("I don't have that information in my knowledge base.") — the signal for questions the KB cannot answer
- `retry_count`: number of guardrail-rejected attempts before the final answer (0 = first attempt accepted)
- `session_id`: optional; passed by `app.py` to link multi-turn conversation records

**Production note:** local JSONL is the current storage. Replace `log_interaction` with a HuggingFace Dataset append when deploying to HF Spaces.

---

### `src/app.py` 🔲

Gradio chat interface wrapping the full agent pipeline. Stateful conversation (history passed each turn). Simple chat window — no retrieval context panel in the user-facing UI.

---

## Data flow (full system)

```
data/knowledge_base/*.md
        │
        ▼
    ingest.py
        │  chunks (enriched, embedded)
        ▼
data/preprocessed_db/          (ChromaDB on disk)
        │
        ▼
    answer.py  ◄──── user query + conversation history
        │  query rewrite → dual retrieval → rerank → generate
        ▼
    agent.py
        ├──► guardrail.py ──► retry if needed (max 2)
        ├──► logger.py    ──► HF Dataset logs
        └──► app.py       ──► Gradio UI ──► user
```

---

## Key constants across modules

| Constant | Value | Location |
|---|---|---|
| `EMBED_MODEL` | `text-embedding-3-large` | `ingest.py` |
| `ENRICH_MODEL` | `gpt-4.1-nano` | `ingest.py` |
| `COLLECTION` | `digital_twin` | `ingest.py` |
| `RETRIEVAL_K` | 20 (planned) | `answer.py` |
| `FINAL_K` | 10 (planned) | `answer.py` |
| Chunk count | 106 | post-ingestion |
| Eval set size | 149 Q&A pairs | `eval/tests.jsonl` |

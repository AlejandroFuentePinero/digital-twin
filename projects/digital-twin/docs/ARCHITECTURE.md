# Digital Twin — Module Architecture

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
│       └── results/           # Versioned eval output files (planned)
│
├── src/
│   ├── ingest.py              # ✅ KB → ChromaDB ingestion pipeline
│   ├── sample_chunks.py       # ✅ Chunk inspection utility
│   ├── answer.py              # 🔲 Retrieval + generation
│   ├── agent.py               # 🔲 Main agent (tools, retry loop)
│   ├── guardrail.py           # 🔲 Quality gate agent
│   ├── logger.py              # 🔲 HuggingFace Dataset logging
│   └── app.py                 # 🔲 Gradio chat UI
│
├── tests/
│   ├── conftest.py            # ✅ sys.path injection for src/
│   ├── test_ingest.py         # ✅ 16 tests for ingest.py
│   └── test_answer.py         # 🔲 Retrieval and generation tests
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

### `src/answer.py` 🔲

The retrieval and generation layer. Takes a user query and conversation history; returns an answer with supporting chunks.

**Planned pipeline:**
1. Rewrite the query with an LLM (refines it for KB search)
2. Embed both the original and rewritten queries
3. Retrieve top-k chunks from ChromaDB for each; merge and deduplicate
4. LLM-rerank the merged set against the original question; select final top-k
5. Pass chunks + conversation history + system prompt to the generation LLM
6. Return answer text + source chunks used

**Constants (starting points, tunable):** `RETRIEVAL_K = 20`, `FINAL_K = 10`

---

### `src/agent.py` 🔲

The main agent. Owns the conversation, calls `answer.py`, receives guardrail feedback, and decides whether to retry.

**Tools available to the agent:**
- `rag_tool` — fetches additional context from ChromaDB when a retry needs more information
- `log_unknown_question` — called when the agent cannot answer from available context; records the question to the HF log
- `log_user_details` — called at conversation end to optionally capture visitor contact details

**Retry logic:** if the guardrail returns `is_acceptable = False`, the agent reattempts (max 2 retries); on persistent failure, returns a canned refusal.

---

### `src/guardrail.py` 🔲

A lightweight LLM call that runs after every answer before it reaches the user.

**Output schema:**
```python
class GuardrailResult(BaseModel):
    is_acceptable: bool
    feedback: str
```

Checks for: prompt injection, personal information leakage, factual errors about Alejandro, tone misrepresentation.

---

### `src/logger.py` 🔲

Writes to three append-only JSONL logs in a private HuggingFace Dataset repository:
- `user_sessions.jsonl` — session ID, question history, contact details, per-answer outcomes
- `unknown_questions.jsonl` — question text, session ID, timestamp
- `unacceptable_answers.jsonl` — question, answer attempts, guardrail feedback, final outcome

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

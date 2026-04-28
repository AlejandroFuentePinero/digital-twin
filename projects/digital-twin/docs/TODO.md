# Digital Twin — TODO

Current project state and active task list. Updated each session.  
For architectural decisions and session logs see `DECISIONS.md`. For component design see `PLAN.md`.

**Last updated:** 2026-04-28  
**Current phase:** Phase 1 complete → Phase 2 (eval baseline) + Phase 3 (guardrail) in progress

---

## Knowledge base — status

The KB is complete and restructured. All 16 files are in `data/knowledge_base/` and the eval set has 149 Q&A pairs in `eval/tests.jsonl`.

KB restructuring completed (session 6): every `##` section is now a self-contained retrieval unit. Five files were restructured — `education.md`, `positioning.md`, `publications.md`, `projects_ai_flagship.md`, `research_projects_detail.md`. `###` subsections were either promoted to `##` or converted to bold inline labels within their parent section.

One deferred item:
- [ ] `agentic_ai_lab.md` — add once the digital twin has a working demo or public form

---

## Phase 1 — Core RAG pipeline

### Ingestion (`ingest.py`) — **done**

- [x] Created `projects/digital-twin/src/` for source files
- [x] `ingest.py` written and verified:
  - [x] `SUMMARY.md` and `INDEX.md` stored as single un-split chunks
  - [x] All other files split on `##` boundaries only (no `###` splits — KB restructured to match)
  - [x] Each chunk enriched with LLM-generated `headline` + one-sentence `summary` (via `gpt-4.1-nano`, parallel with `ThreadPoolExecutor`)
  - [x] Embedded document: `headline + summary + original_text` (retrieval boost + generation context)
  - [x] Metadata: `source_file`, `section_heading`, `heading_level`, `category`, `headline`, `summary`
  - [x] Embedded with `text-embedding-3-large`
  - [x] Stored in ChromaDB `PersistentClient` at `data/preprocessed_db/`, collection `digital_twin`
  - [x] Re-ingest is idempotent (delete + recreate collection)
- [x] `sample_chunks.py` — inspection utility: sample N random chunks with optional `--category` / `--source` / `--seed` filters
- [x] `tests/test_ingest.py` — 17 tests covering chunking, unsplit behaviour, metadata, enrichment, prompt context, and `enrich_all` order preservation (all passing)
- [x] Verified: 106 chunks across 14 categories; SUMMARY.md and INDEX.md confirmed as un-split whole-document chunks

### Retrieval and generation (`answer.py`) — **done**

- [x] `fetch_context_unranked` — embed query with `text-embedding-3-large`, retrieve top-20 chunks
- [x] `rewrite_query` — LLM rewrites query for KB search; uses last 2 conversation turns for context
- [x] `fetch_context` — dual retrieval (original + rewritten), merge + deduplicate, LLM rerank, return top-10
- [x] `rerank` — structured output (`RankOrder`) with out-of-range / duplicate ID guard
- [x] System prompt — scoped to professional background only; explicit in/out-of-scope lists; injection-resistant (named attack patterns, context-as-information-only rule)
- [x] `make_rag_messages` — context labelled with `source_file` + `section_heading`; history threaded through
- [x] `answer_question(question, history)` — main entry point; returns `(answer_str, chunks)` for eval
- [x] `tenacity` retry on all LLM calls (`wait_exponential`, max 120s)

### Chat UI (`app.py`)

- [ ] Gradio chat interface wrapping `answer_with_guardrail`
- [ ] Stateful conversation (pass history each turn)
- [ ] Run locally, smoke test with 5–10 questions from the eval set

---

## Phase 2 — Evaluation baseline

- [ ] Write `eval/run_eval.py`: iterate over `tests.jsonl`, call answer pipeline, collect outputs
- [ ] Retrieval metrics: MRR, nDCG, keyword coverage (per category + aggregate)
- [ ] Answer metrics: LLM-as-judge (accuracy, completeness, relevance, appropriateness — 1–5)
- [ ] Write results to `eval/results/v1_{date}.json` with architecture notes field
- [ ] Review results, identify weakest categories

---

## Phase 3 — Guardrail and agent tooling

- [x] Guardrail agent: `{is_acceptable: bool, feedback: str}` after every answer
- [x] Retry loop in `answer_with_guardrail` (max 2 retries, canned refusal on exhaustion)
- [ ] `log_unknown_question` tool wired to HF Dataset JSONL
- [ ] `log_user_details` tool with Pydantic model (name, company, role, email, phone — all optional)
- [ ] All three HF Dataset logs writing correctly; session linkage intact

---

## Phase 4 — Tuning

Driven by Phase 2 eval results. No tasks until baseline is established.

- [ ] Tune chunk granularity (current: `##` only) if retrieval precision is poor
- [ ] Tune retrieval-k and final-k
- [ ] Tune reranking prompt
- [ ] Re-run eval and version results after each meaningful change

---

## Phase 5 — Deployment

- [ ] Package for HuggingFace Spaces
- [ ] Configure Space secrets (OPENAI_API_KEY, HF write token)
- [ ] Smoke test full flow (guardrail, logging, latency)
- [ ] Link Space from portfolio

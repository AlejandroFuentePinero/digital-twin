# Digital Twin — TODO

Current project state and active task list. Updated each session.  
For architectural decisions and session logs see `DECISIONS.md`. For component design see `PLAN.md`.

**Last updated:** 2026-04-28  
**Current phase:** Phase 2 + 3 complete → Phase 4 (tuning + KB enrichment)

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

### Chat UI (`app.py`) — **done**

- [x] Gradio chat interface wrapping `answer_with_guardrail`
- [x] Stateful conversation (pass history each turn)
- [x] History truncated to last 10 turns to cap context window
- [x] Smoke tested locally

---

## Phase 2 — Evaluation baseline

- [x] Write `eval/run_eval.py`: iterate over `tests.jsonl`, call answer pipeline, collect outputs
- [x] Retrieval metrics: MRR, nDCG, keyword coverage (per category + aggregate)
- [x] Answer metrics: LLM-as-judge (accuracy, completeness, relevance — 1–5)
- [x] Results written to `eval/results/v{N}_{date}.json` — auto-versioned with full architecture snapshot
- [x] Gap rate tracked: fraction of questions where system responded "I don't know"
- [x] v1 baseline (gpt-4.1-nano): MRR=0.804, acc=3.95, gap=14.1%
- [x] v2 (gpt-4.1 + reasoning prompt + KB fixes): MRR=0.865, acc=4.48, gap=0.0%
- [x] v3 (Claude Sonnet guardrail + fresh ingest): MRR=0.868, acc=4.46, gap=0.7%
- [x] Cross-run category comparison plot: `eval/results/comparison.png`
- [x] Weaknesses identified: temporal (MRR 0.78, cov 80%), numerical completeness (3.94/5)

---

## Phase 3 — Guardrail and agent tooling

- [x] Guardrail agent: `{is_acceptable: bool, feedback: str}` after every answer
- [x] Guardrail switched to Claude Sonnet 4.6 — different model family from GPT-4.1 generator to avoid sycophancy/correlated failures
- [x] Retry loop consolidated into single `for attempt in range(MAX_ATTEMPTS=3)` loop
- [x] Interaction logger: append-only JSONL at `data/logs/interactions.jsonl` — every call
  logged with question, answer, is_acceptable, knew_answer, retry_count, session_id
  TODO (production): replace local JSONL with HuggingFace Dataset write when deploying to HF Spaces
- [x] `stop_after_attempt(5)` added to all tenacity retry decorators — prevents infinite loops on persistent API errors
- [x] Query rewriting downgraded to `gpt-4.1-nano` (simple task; full model kept for generation and reranking)
- [ ] `log_user_details` tool with Pydantic model (name, company, role, email, phone — all optional)

---

## Phase 4 — KB Enrichment and Tuning

### KB gaps identified from eval (priority order)

- [ ] **Temporal retrieval (MRR 0.783, coverage 80%)** — Add `## Career Timeline` section to `experience.md` or a dedicated `timeline.md` listing every role with explicit start/end years so dates surface in chunk headlines. Current prose buries dates.
- [ ] **Numerical completeness (3.94/5)** — Add one line to SYSTEM_PROMPT: when a question asks for counts or metrics, include the specific numbers. Generation is finding the chunks but omitting figures.

### New KB file: `strengths_and_gaps.md`

The most important missing KB file for recruiter conversations. Should cover:

- [ ] **Verified strengths** — what Alejandro demonstrably does better than most candidates at his level (uncertainty quantification, eval-first engineering, cross-domain synthesis, scientific rigour applied to ML). Concrete evidence for each.
- [ ] **Explicit CV gaps with honest framing** — frontend/React, DevOps/CI-CD pipelines, cloud platforms (AWS/GCP/Azure production deployment). For each: current state, what he has done in adjacent areas, what he is actively working on. The system should surface these proactively when relevant rather than waiting to be asked.
- [ ] **Guardrail update** — when a question touches a known gap area, the system should acknowledge it directly and give the "actively working on" context rather than deflecting or staying silent.

### New eval questions: recruiter and behavioural

The current eval set (149 questions) covers factual retrieval well but has no recruiter-style or behavioural questions. Add a new batch covering:

- [ ] **Behavioural** — "Tell me about a time you failed and what you learned", "Describe a conflict with a collaborator and how you resolved it", "What's your biggest professional weakness?", "Tell me about a time you had to deliver under pressure"
- [ ] **Tricky/positioning** — "Why are you transitioning from ecology to AI?", "You have no industry experience — why should we hire you over someone who does?", "What does a team look like where you do your best work?", "Where do you see yourself in 5 years?", "Why no frontend or cloud experience?", "Have you ever shipped something to production used by real users?"
- [ ] **Gap-aware** — "Do you have experience with AWS/GCP?", "Have you worked with Docker/Kubernetes?", "Do you have React or frontend experience?" — these should trigger the proactive gap acknowledgement with active-learning framing
- [ ] **Salary/logistics** — out-of-scope questions should redirect gracefully, not refuse bluntly

### Tuning

- [ ] Tune retrieval-k and final-k once recruiter questions are in the eval set
- [ ] Re-run eval and version results after each meaningful change

---

## Phase 5 — Deployment

- [ ] Package for HuggingFace Spaces
- [ ] Configure Space secrets (OPENAI_API_KEY, HF write token)
- [ ] Smoke test full flow (guardrail, logging, latency)
- [ ] Link Space from portfolio

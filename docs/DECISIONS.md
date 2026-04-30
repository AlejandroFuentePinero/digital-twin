# Digital Twin — Decisions Log

**Project:** AI chat system representing Alejandro de la Fuente professionally  
**Core concept:** A conversational agent that answers recruiter and professional questions about skills, experience, projects, and research — with enough depth to be genuinely useful, and links to go deeper.

---

## Session 15 (2026-04-30) — Dashboard PRD #7 closed out

**Status:** Wraps the developer-experience layer started in Session 13. PRD [`#7`](https://github.com/AlejandroFuentePinero/digital-twin/issues/7) and all five sub-issues now closed.

### What shipped

- **[`#10`](https://github.com/AlejandroFuentePinero/digital-twin/issues/10) — Docstring-driven labels + inline tracebacks** (commit `aa60c97`). Test labels resolve from each test function's docstring via `ast.parse`, with the humanized name as fallback. Failed tests render their short traceback inline under the badge in a styled `<pre>` block — no click required.
- **[`#11`](https://github.com/AlejandroFuentePinero/digital-twin/issues/11) — Top strip, Run-all button, cached-report fallback** (commit `3512e09`). New pure helpers `summarize()` (counts/duration/timestamp/global indicator) and `render_summary()` (top-strip markdown). New `gather_report(runner, cache_path)` runs pytest and falls back to the cached JSON on launch failure, returning an empty report when no cache exists so the Gradio app cannot crash on cold start. `build_app()` rewired to expose error banner + summary + Run-all button + module body, all refreshed atomically on click.
- **PRD [`#7`](https://github.com/AlejandroFuentePinero/digital-twin/issues/7) closed.** All five children done: #8 (MVP dashboard), #9 (failure-path tests), #10 (labels + tracebacks), #11 (strip + Run-all + fallback), #12 (testing convention). Every user story in the PRD is delivered.

### Design decisions

- **`gather_report` takes the runner as a parameter.** Keeps the cached-report fallback testable without spawning a real pytest subprocess. Default arg is `run_pytest`, so production callers don't notice.
- **Empty-report sentinel (`{"summary": {}, "tests": []}`)** is the no-cache fallback rather than `None`. Both `summarize()` and `parse_report()` already tolerate it, so downstream renderers don't need a special-case branch.
- **Wiring stays untested.** Per the convention codified in #12, `build_app()` and `run_pytest()` remain on the partial-exemption list. The 10 new tests all cover pure helpers (`summarize`, `render_summary`, `gather_report`).

### Verified

- Full suite: `uv run pytest tests/ -q` → **136 passed**. `tests/test_module_health.py` grew 17 → 27.
- Smoke test: `gather_report(runner=lambda: ...)` happy path, runner-fails-with-cache fallback, runner-fails-without-cache no-crash.
- Dashboard launches: `build_app()` returns a `gr.Blocks` instance with the new wiring (top strip, Run-all button, body, error banner).

---

## Session 14 (2026-04-30) — Repo flatten to standalone, dependency prune

**Status:** Infrastructure cleanup. No code logic changed.

### What was done

- **Flattened `projects/digital-twin/*` to repo root** (commit `dcac88a`). The project now lives in its own `digital-twin` repo instead of nested under `portfolio/AI-projects/projects/digital-twin/`. Triggered VSCode reload, which triggered `uv sync`, which failed building `av` (PyAV needs ffmpeg7 + pkg-config) and gutted the venv.
- **Pruned `pyproject.toml`** from 30 → 11 runtime deps. Removed course leftovers that were never imported by `src/`, `tests/`, or `eval/`: `autogen-*`, `langchain-*`, `langgraph*`, `mcp*`, `openai-agents`, `playwright`, `polygon-api-client`, `semantic-kernel`, `sendgrid`, `smithery`, `speedtest-cli`, `wikipedia`, `bs4`, `lxml`, `pypdf*`, `ipywidgets`. The `av` build chain is gone with `semantic-kernel`. Cross-checked against `grep -rohE "^(from|import)"` over `src/`, `tests/`, `eval/`. `uv.lock` shrank by ~2,300 lines.
- **Fixed `eval/run_eval.py:300`** — `Path(__file__).parent.parent.parent.parent` (correct under the old depth-4 location) walked past the new repo root. Reduced to `parent.parent`.
- **Fixed cross-doc relative links** in `docs/TODO.md`, `docs/ARCHITECTURE.md`, `docs/PLAN.md`, `docs/DECISIONS.md` — `../../../CONTEXT.md` → `../CONTEXT.md` and `../../../docs/adr/...` → `./adr/...`.

### Why

The flatten was not a refactor; it was a packaging move so the project can ship as its own GitHub repo. The dependency prune was forced by the venv breakage but is the right state regardless: every removed package was dead weight from the course-era `example/rag-example/` reference implementation.

### Verified

- `uv run python -m pytest tests/ -q` → **110 passed in 13.52s** (same as the last green run pre-flatten).
- `module_health` pipeline: 110/110 across 6 modules (answer 35, eval 26, ingest 17, guardrail 13, logger 12, module_health 7).
- All `Path(__file__).parent.parent / "data" / ...` constants resolve to real dirs at the new depth.

---

## Session 13 (2026-04-29) — Test-status dashboard + testing convention

**Status:** Developer-experience layer added on top of the architecture established in Session 12. Does not change any of the ADRs.

### What was decided

A local Gradio dashboard for at-a-glance suite health, plus a written testing convention. Driven by [`#7`](https://github.com/AlejandroFuentePinero/digital-twin/issues/7) (PRD), shipped as two slices [`#8`](https://github.com/AlejandroFuentePinero/digital-twin/issues/8) (MVP dashboard) and [`#12`](https://github.com/AlejandroFuentePinero/digital-twin/issues/12) (convention codified). Both closed in commit `966bdfc`.

**Motivation (from #7):** as the system grows module-by-module, regressions in older modules slip through unnoticed when the only signal is a terminal `pytest` output read once per change. The dashboard makes the whole suite always-visible.

### What shipped

- **`src/module_health.py`** — single-file Gradio app. On launch, runs `pytest --json-report --json-report-file=.module_health_report.json --tb=short` via subprocess (does not import pytest as a library), parses the JSON report into Module/Test domain types, and renders one always-visible block per `test_*.py` with a header `<module> · X/Y` and a coloured `PASS` / `FAIL` / `ERROR` / `SKIP` badge per test. Filename intentionally avoids `test_*.py` / `*_test.py` so pytest doesn't auto-collect it and accidentally launch the Gradio app. Cached report at `.module_health_report.json` (gitignored).
- **`docs/TESTING.md`** — written-down convention: every `*.py` under `src/` and `eval/` has a matching `tests/test_<module>.py` with at least one functional test; mock only at I/O boundaries; pure functions tested directly with no mocks; **no LLM API calls in any test under any circumstances**; new `test_*.py` files appear in the dashboard automatically (filename discovery, no registration). Exemption list: `app.py`, `sample_chunks.py`, `plot_eval.py` (pure glue); `module_health.py` is a partial exemption (pure helpers tested, Gradio/subprocess wiring not).
- **`CLAUDE.md`** — gained a one-line pointer to `docs/TESTING.md` and the dashboard command.
- **Two failure-path tests added** to bring the suite up to the convention: malformed-response handling for `guardrail.evaluate` and for `ingest.enrich_chunk`.

### Design decisions

- **Subprocess over library invocation.** Importing pytest as a library would mean inheriting its plugin state and obscuring whether the suite genuinely passes when run the normal way. Subprocess matches the developer's mental model: "the dashboard shows what `pytest` would tell me."
- **Filename-driven discovery, no config list.** A new `test_*.py` file appears in the dashboard with no registration step. Forces naming discipline in exchange for zero ongoing maintenance.
- **No tests for `module_health.py` as a whole.** The dashboard is tooling, same exemption category as `app.py`. Pure helpers (`humanize`, `parse_report`) are covered in `tests/test_module_health.py`; Gradio rendering and subprocess wiring are not.
- **Dashboard does not gate CI.** Local development tool, not infrastructure.
- **Convention lives in two places by design.** Repo-root `CLAUDE.md` carries the pointer (so any future agent finds it); `docs/TESTING.md` carries the full treatment (so additions to the exemption list are visible in one canonical place). Brief in `CLAUDE.md`, full in `TESTING.md`, no duplication.

### What survives unchanged

- ADRs 0001–0003 — this layer is orthogonal to the routing redesign.
- All existing test files. The two failure-path additions (#7 testing decisions) raised coverage without rewrites.

---

## Session 12 (2026-04-29) — Architectural Redesign: Classify-then-Route

**Status:** This session is the project's tipping point. The existing codebase (Sessions 1–11) is treated as pre-redesign and will be substantially rewritten. See `feedback_redesign_over_patching.md` in auto-memory for the persistent rule.

### What was decided

A multi-hour interview session (`/grill-with-docs`) walked the entire design tree and produced a unified architecture. Canonical artifacts:

- **[`CONTEXT.md`](../CONTEXT.md)** — 18-term glossary covering Visitor, Gap question, Broader skill, Active learning, Gap-aware response, Gap phrase, Knowledge base, Guardrail, Always-on profile, Frame, Substance, Calibration ladder, Deflection, Sentinel, Interaction log, Branch, Classifier, Tool registry, Contact-provided flag.
- **[`docs/adr/0001-always-on-profile-and-kb-as-depth.md`](./adr/0001-always-on-profile-and-kb-as-depth.md)** — Frame/Substance split. `profile.md` is the always-on Frame (~2–2.5k tokens); KB is retrieved Substance. Source files are content-separated (profile carries patterns; SUMMARY carries numbers; positioning carries parallels) so there is no duplicate source of truth. *Partially superseded by ADR-0003 on the injection mechanism — see below.*
- **[`docs/adr/0002-hf-dataset-as-canonical-log-store.md`](./adr/0002-hf-dataset-as-canonical-log-store.md)** — HuggingFace Dataset is the production log store. Local JSONL is dev-only. `LogReader` abstraction supports both backends.
- **[`docs/adr/0003-classify-then-route-orchestration.md`](./adr/0003-classify-then-route-orchestration.md)** — A cheap classifier picks one of five branches (`GAP`, `BEHAVIOURAL`, `TECHNICAL`, `GENERIC`, `LOGISTICAL`) per turn. Each branch loads its own `profile.md` sections, retrieval depth, and tools. Replaces the monolithic system prompt to direct attention and bound cognitive load on cheaper models — a known failure mode from prior projects.

### Key rules established this session

1. **Bar for content:** would Alejandro say this verbatim to a recruiter on a phone call? If no, deflect. Never invent stories or credentials.
2. **Calibration ladder** (soft, taught in prompt, not enforced verb-by-verb): KB evidence pattern → claim verb. `skill + project + role → expertise`; `skill + project → hands-on`; `skill + course only → trained`; `skill listed only → exposure`; `nothing in KB → gap phrase`. Domain (research vs AI) is *not* split — academic skills are presented as transferable.
3. **Gap-aware response:** for known gaps, lead with the broader skill the question probes (with named, KB-verifiable evidence), then honestly state the specific gap with explicit exposure phrasing, then name active learning with concrete credentials. Never deflect, never inflate.
4. **Deflection** is reserved for behavioural-story requests (failure, conflict, pressure) where Alejandro has not authorised a specific story for the agent to tell. Distinct from the Gap phrase (KB has nothing) and from a Gap-aware response (KB has structured info on a known gap).
5. **`log_user_details` invitation triggers:** (a) attached to deflection, (b) once at turn 3 of a session, integrated into the answer naturally. Both paths suppressed once `contact_provided = True`.
6. **Eval questions must be KB-grounded.** Recruiter / behavioural questions land in eval only after corresponding KB content exists.

### Phase plan

The 5-phase plan in `PLAN.md` is replaced by a 7-phase plan in `TODO.md`:

1. Profile + KB content rewrites
2. Routing + new pipeline (rewrites of `answer.py`, `guardrail.py`, `logger.py`; new `classifier.py`, branch composers, `LogReader`, tool)
3. Re-eval baseline (v4)
4. Sentinel + LLM failure summaries
5. Break the live system (probe + targeted KB additions)
6. HF Dataset migration
7. Deploy

### What survives from the pre-redesign codebase

- `ingest.py` and the chunking strategy (build on)
- KB folder structure and most KB files (most build on; some rewrites)
- `eval/run_eval.py` and `eval/tests.jsonl` (build on; result schema gains a `branch` column)
- ChromaDB store (rebuilt on profile.md changes)
- `tests/test_ingest.py` (survives; ~70% of the rest of the test suite is rebuilt)

### Closing context

Alejandro will review the codebase next, applying the redesign-over-patching rule from auto-memory. The four pre-redesign docs in `docs/` are kept as historical record; `TODO.md` is the active source of truth, with ADRs and CONTEXT.md as canonical references.

---

## Session 6 (2026-04-28) — KB Restructuring and ## Only Chunking Strategy

### Decision: restructure KB so every ## section is a self-contained retrieval unit

**Problem:** The initial chunking strategy used both ## and ### boundaries. This produced poor chunks: grouping headers like `## First-author peer-reviewed papers` had no body content (near-empty chunks), and case-study subsections like `### Problem`, `### Approach`, `### Results` were valid text but wrong granularity — retrieving "Results" from one project without its context is useless.

**Alternative considered:** Patch the code with `MIN_WORDS = 15` filter and `H2_ONLY_FILES` special-casing. Rejected: patching the symptom. The issue is in the data structure, not the splitter.

**Decision:** Restructure the KB so every ## section is complete and meaningful in isolation. The fix lives in the data, not the code. ### headings become body text within ## sections.

**Changes to KB files:**
- `publications.md` — papers promoted from ### to ##; empty grouping headers removed; preamble URLs given their own ## section
- `education.md` — PhD/MSc/BSc promoted from ### to ##; `## Formal Degrees` grouping header removed
- `positioning.md` — 5 transfer mechanisms promoted from ### to ## with "Transfer:" prefix; empty `## What specifically transfers` removed
- `projects_ai_flagship.md` — all ### subsections promoted to ##; numbered headings renamed for clarity
- `research_projects_detail.md` — `### Problem/Approach/Stack/Results/Impact` replaced with **bold inline labels**; each project remains a single ## section

**Changes to code:**
- `ingest.py` — simplified to `r"^(#{2}) (.+)"` pattern only; removed `H2_ONLY_FILES`, `MIN_WORDS`, and associated special-casing
- `tests/test_ingest.py` — updated to reflect ### no longer splits; removed tests for removed special cases; 16/16 passing

---

## Session 11 (2026-04-28) — Model Upgrades, Code Quality Fixes, Eval v2/v3, Comparison Plot

### What was built

**Model upgrades:**
- Answer model: `gpt-4.1-nano` → `gpt-4.1` — big quality jump; gap rate collapsed from 14.1% to 0%
- Guardrail model: `gpt-4.1-nano` → `anthropic/claude-sonnet-4-6` — different model family to avoid sycophancy and correlated evaluation failures. Interview story: "I deliberately use a different model family for the judge."
- Query rewrite model: kept at `gpt-4.1-nano` — simple task that doesn't benefit from a stronger model; cost saving
- Reranking stays on `gpt-4.1` — this is where quality is most sensitive

**Code quality fixes (from Opus architectural review):**
- `stop_after_attempt(5)` added to all `@retry` decorators in `answer.py`, `guardrail.py`, `run_eval.py` — previously would loop forever on persistent API errors
- `_format_context` double-call eliminated: `answer_with_guardrail` now formats context once and passes the string through to both the guardrail and generation calls. `make_rag_messages` and `_rerun` signatures changed from `chunks: list[Chunk]` to `context: str`
- `MAX_RETRIES` → `MAX_ATTEMPTS = 3`: the old loop had a duplicated final `evaluate()` call outside the loop (fragile). Consolidated into a single `for attempt in range(MAX_ATTEMPTS)` loop; rerun only fires if `attempt < MAX_ATTEMPTS - 1`
- `REWRITE_MODEL = "openai/gpt-4.1-nano"` extracted as a separate constant — makes model assignment explicit
- History truncation in `app.py`: last 10 turns only passed to the pipeline, preventing silent context-window exhaustion on long sessions

**Eval runs:**
- v2 (gpt-4.1 + reasoning prompt + KB fixes): MRR=0.865, acc=4.48, gap=0.0%
- v3 (Claude Sonnet guardrail + fresh ingest + all code fixes): MRR=0.868, acc=4.46, gap=0.7%
- Tiny score variance v2→v3 is expected judge variability (different model family, different calibration)

**Cross-run comparison plot:** `eval/plot_eval.py` — loads all `v*.json` result files, produces a 3×3 grid: retrieval metrics (MRR, nDCG, coverage) × categories, answer metrics (accuracy, completeness, relevance) × categories, plus overall trend lines and gap rate bar chart. `--runs` and `--output` flags. Saved to `eval/results/comparison.png`.

### Architectural decisions

**Skipped from Opus review:**
- Hybrid BM25 + cross-encoder: KB is 107 chunks, MRR already 0.868. BM25 adds a separate index to maintain with marginal gain on a small curated corpus. Cross-encoder adds a model dependency. Both become relevant if the KB grows to thousands of chunks or if retrieval starts degrading.
- Full async pipeline: single-user portfolio app, sequential adds ~200ms, not felt.
- Streaming: valid UX improvement, deferred to deployment phase.
- Rate limiting, PII handling, HF Dataset migration: all deployment-phase concerns.

### Weakness analysis from eval data
- **Holistic MRR 0.727 is a metric artifact.** Answer quality is 4.67/5 — the system handles holistic questions well. MRR penalises queries whose keywords are naturally distributed across the KB. No fix needed.
- **Temporal MRR 0.783, coverage 80% — KB structure issue.** Dates buried in prose don't surface in chunk headlines. Fix: dedicated timeline section with explicit year anchors.
- **Numerical completeness 3.94/5 — generation behaviour.** Retrieval is finding the right chunks (MRR 0.863). Model drops specific numbers in answers. Fix: targeted SYSTEM_PROMPT instruction.

---

## Session 10 (2026-04-28) — Agentic AI Retrieval Fix + System Prompt Reasoning Unlock

### Problem
Two related issues caused the system to fail on valid, in-scope questions:

1. **Over-constrained system prompt.** Framing the model as a "lookup tool" with strict "answer only from retrieved context" wording prevented synthesis queries like "what are Alejandro's top publications?" and regional queries like "experience in South America". The model refused rather than reasoned.

2. **Chunk headline mismatch for agentic AI content.** The `projects_ai_flagship.md` LLM Price Predictor `##` section had 7 numbered stages; the autonomous agent system was stage 6. The LLM enrichment headline for that chunk read "An end-to-end ML system forecasting Amazon prices using RAG and ensemble modeling" — no agentic signal. For "tell me about a project using agentic AI", the reranker surfaced "Flight Booking Agentic Tool" (rank 2 via "Other Supporting Projects" chunk) instead of the actual flagship autonomous agent system.

### Fixes

**KB fix — `experience.md`:** Added "South America" to section headings for Bolivia, Chile, and Peru roles (e.g. `**2017 – 2018 | Bolivia, South America**`) and to "Peru (South America)" in field experience. Regional query now surfaces the correct chunks.

**KB fix — `projects_ai_flagship.md`:** Added a dedicated `## LLM Price Predictor — Autonomous Agent System` section between LLM Price Predictor and Expert Knowledge Worker. This section describes the AutonomousPlanningAgent, ScannerAgent, EnsembleAgent, MessagingAgent, and agentic design patterns (LLM-as-planner, tool use, continuous operation, observability). At re-ingest, this gets its own chunk with its own enriched headline — now rank 1 for "agentic AI" queries.

**System prompt rewrite (`src/answer.py`):** Replaced lookup-tool framing with reasoning-agent framing. Key changes:
- "use it to think, synthesise, and give genuinely useful answers" instead of "answer solely from the retrieved context"
- `## How to answer` section added: reason over context, use partial context, gap phrase as last resort only, no fabrication
- Gap phrase instruction changed from "say so directly" to "last resort only — only if retrieved context contains nothing relevant at all"

**Re-ingest:** 107 chunks (up from 106); projects category grew from 13 to 14 chunks. Verified: "tell me about a project using agentic AI" retrieves autonomous agent chunk as rank 1 and generates a correct, detailed answer naming ScannerAgent/EnsembleAgent/AutonomousPlanningAgent.

### Eval v2 needed
Both the prompt rewrite and KB changes justify a v2 eval run to quantify improvement in gap rate and answer quality.

---

## Session 9 (2026-04-28) — Evaluation Pipeline

### What was built

**`eval/run_eval.py`** — full evaluation pipeline. Loads `tests.jsonl`, runs every question through retrieval and answer pipelines, computes metrics, and writes a versioned result file.

**Retrieval metrics (per question, per category, overall):**
- MRR (Mean Reciprocal Rank) — average across all keywords in the test question
- nDCG (Normalised Discounted Cumulative Gain, binary relevance, k=10) — average across keywords
- Keyword coverage — percentage of keywords found anywhere in the top-k results

**Answer metrics (LLM-as-judge, 1–5):**
- Accuracy — factual correctness vs reference answer; any factual error scores 1
- Completeness — covers all information in the reference answer
- Relevance — directly answers the question with no padding

**Gap rate** — fraction of questions where the system responded with `GAP_PHRASE` ("I don't know"); tracked in summary alongside answer quality.

**Result file:** `eval/results/v{N}_{date}.json`. Auto-versioned (max existing N + 1). Includes full architecture snapshot (model, embed model, RETRIEVAL_K, FINAL_K, chunk count from ChromaDB, KB files from disk, notes). Snapshots are runtime-generated — never stale.

**System prompt hardened**: "I don't know" instruction now says "use this exact wording verbatim — it is used for logging and gap tracking" to prevent paraphrasing that would break gap detection.

**`tests/test_eval.py`** — 26 tests. Covers: `_reciprocal_rank` (case-insensitive, position, empty), `_dcg` (rank weighting, k cutoff), `_ndcg` (perfect, zero, partial), `_mean`, `_agg_retrieval/_agg_answer`, `_next_version` (versioning logic), `load_tests` (JSONL parse, blank lines), `eval_retrieval` (mocked fetch_context).

**All 103 tests passing.**

### Design decisions

**`EvalQuestion` not `TestQuestion`** — renamed to avoid pytest treating it as a test class (warning suppression).

**`answer_question` not `answer_with_guardrail` for eval** — the guardrail is a safety gate, not a quality improvement. Evaluating raw answer quality gives a cleaner signal; guardrail acceptance rate is a separate concern.

**Architecture snapshot at runtime** — chunk count from live ChromaDB, KB files from disk. This is always accurate and removes the risk of stale documentation diverging from reality.

**Gap rate in summary** — surfaces knowledge gaps immediately in the printed output, without needing to scan per-question records.

---

## Session 8 (2026-04-28) — Interaction Logger

### What was built

**`src/logger.py`** — append-only JSONL interaction logger. One record per `answer_with_guardrail` call: `timestamp`, `session_id`, `question`, `answer`, `is_acceptable`, `knew_answer`, `retry_count`. Creates `data/logs/` on first write. `data/logs/` is gitignored.

**`src/answer.py` updates:**
- `GAP_PHRASE` extracted as a named constant (must match the phrase in `SYSTEM_PROMPT` exactly)
- `answer_with_guardrail` gains `session_id: str | None` param
- `retry_count` tracked through the loop
- `log_interaction` called at every exit point (first-attempt accept, post-retry accept, canned refusal)
- `knew_answer` checked against the last generated answer (not `CANNED_REFUSAL`) so it reflects whether the KB had the information, not whether the guardrail accepted

**`tests/test_logger.py`** — 13 tests using `tmp_path` + `monkeypatch` to redirect `LOG_PATH`. Covers: field presence, value correctness, timestamp format, `knew_answer` detection, append behaviour, valid JSON per line, directory auto-creation, retry_count, is_acceptable.

**`tests/test_answer.py`** — 4 existing `answer_with_guardrail` tests patched to mock `log_interaction`; 4 new tests: logs once per call, logs correct retry_count, logs `knew_answer=False` for gap phrase, passes session_id through.

**All 77 tests passing.**

### Design decisions

**No agent layer needed.** The retry loop already lives in `answer_with_guardrail`, so logging can wire directly there. `agent.py` stays planned for tool-calling (contact capture, user details) but is not required for usage tracking.

**Local JSONL now, HF Dataset later.** Single function to replace when deploying; no other code changes needed.

**`knew_answer` checked on the generated answer, not `CANNED_REFUSAL`.** When the canned refusal is returned it's because the guardrail repeatedly rejected, not necessarily because the KB lacked information. Checking the last generated answer gives the correct signal.

---

## Session 7 (2026-04-28) — Guardrail Agent and Retry Loop

### What was built

**`src/guardrail.py`** — Lightweight LLM evaluator. Receives the question, generated answer, conversation history, and the formatted context string passed to the answer model. Returns `Evaluation(is_acceptable: bool, feedback: str)`. Structured output via Pydantic + `response_format`. Six evaluation criteria: factual accuracy, scope, no fabrication, honesty about gaps, professional tone, injection resistance.

Key design: evaluator receives the **same context string used by the answer model** so it can fact-check claims against KB content rather than general knowledge.

**`src/answer.py` updates:**
- `SYSTEM_PROMPT` — "say so directly: 'I don't have that information in my knowledge base.'" added as the explicit gap-signal phrase; tracked for unknown question logging
- `MAX_RETRIES = 2`, `CANNED_REFUSAL` constant added
- `_rerun(question, history, chunks, previous_answer, feedback)` — retry generation with previous answer + feedback appended to the system prompt under `## Previous answer rejected`
- `answer_with_guardrail(question, history)` — full pipeline: generate → evaluate → rerun up to MAX_RETRIES times → final evaluate → canned refusal on exhaustion

**`tests/test_guardrail.py`** — 13 tests: 6 for `_build_user_prompt` (content inclusion, history role labels, empty history), 7 for `evaluate` (return type, accept/reject paths, prompt content, system message position, response_format kwarg).

**`tests/test_answer.py`** — expanded with 8 new tests: 4 for `_rerun` (feedback and previous answer in system prompt, history threading, return value), 4 for `answer_with_guardrail` retry loop (returns on first accept, retries on rejection, canned refusal after exhaustion, evaluation call count bounded by MAX_RETRIES + 1).

**All 61 tests passing.**

### Design decisions

**Guardrail receives formatted context string, not raw chunks.** The evaluator needs to check factual claims against actual KB content. Passing the same formatted context string the answer model saw is the simplest way to achieve this without re-embedding.

**`_rerun` appends to system prompt, not as a separate message.** Keeping rejection context in the system message avoids polluting the conversation history that the answer model will see, and ensures the model treats it as instructions rather than conversation.

**Explicit gap phrase.** "I don't have that information in my knowledge base." is a trackable string — future logging can detect it and route questions to `log_unknown_question` without LLM classification overhead.

---

## Session 5 (2026-04-25) — Full raw_me Audit and Link Completeness

### What was audited
All 61 raw_me files checked systematically against every KB file. Verdict: no meaningful content gaps remain. Four targeted fixes applied.

### Changes made
- `publications.md` — added DOI for Iriarte et al. 2021 (viscacha, URL: ojs.sarem.org.ar), PDF download link for Gallardo et al. 2018, Dryad search URL in header
- `education.md` — added MSc thesis title ("Implementation of GIS and species distribution models on studies of niche marginality of threatened plants") and its methodological significance as precursor to PhD SDM work
- `projects_ai_flagship.md` — added Engineering Patterns section (6 cross-cutting patterns from llm-engineering-lab.md portfolio page: prompt contracts, stage-based orchestration, evaluation-first, observability, workflow-ready outputs, resumable async jobs); added explicit HuggingFace dataset names for LLM Price Predictor
- `INDEX.md` — added academic portfolio URL, ORCID direct URL, Dryad search URL, Bird population trends Shiny app URL

### Files confirmed complete (no changes needed)
research_overview, research_projects_detail, recognition, teaching, talks, personal, positioning, skills, experience, identity, projects_skill_labs — all confirmed complete against their raw sources.

### Files with no unique content (skipped)
datascience-communication.md, datascience-projects.md, academic.md (navigation pages); mlb_analytics_sql.md, python-ML-projects.md, python_oop_minisystems.md, python_eda_mini_projects.md (portfolio pages already covered); relevant_links.txt (3 links already in INDEX); summary.txt (2 lines, nothing new).

### Eval: 143 → 149 questions (+6)

---

## Session 4 (2026-04-25) — Personal Content, Project Depth, Production Signals

### What was built

**New KB file:**
- `personal.md` — character, volunteering history as character evidence (wildlife rehab Spain/Portugal/Peru/Bolivia/UK, primate rescue, big cat monitoring), hobbies (MTG, wildlife), working style, what he's looking for

**Enriched existing files:**
- `projects_ai_flagship.md` — Expert Knowledge Worker elevated to full technical section: baseline vs optimised pipeline, LLM-based chunking (headline/summary/original_text), hierarchical RAG via category summaries, query rewriting + LLM reranking, full evaluation system (MRR + nDCG + LLM-as-judge)
- `projects_ai_flagship.md` — AI-JIE: added `instructor` library role, LLM-as-judge v9g baseline (2.98/3.00), eval tracking in eval_results/, GitHub Actions CI, unit tests (idempotency + corruption tolerance)
- `INDEX.md` — added personal.md

**Eval set expanded: 130 → 143 questions (+13)**
- New questions cover: personal.md (5), Expert Knowledge Worker depth (4), AI-JIE CI/evaluation (3), character/working style (1)

---

## Session 3 (2026-04-25) — AI/DS Content Enrichment and Eval Expansion

### What was built

**New KB file:**
- `positioning.md` — explicit bridge narrative: the 5 transfer mechanisms (evaluation discipline, uncertainty quantification, first-principles framing, systems-level thinking, transparent communication), concrete research↔AI parallels table, what Alejandro does not bring

**Enriched existing files:**
- `projects_ai_flagship.md` — Job Intelligence Engine: full 5-stage pipeline architecture added (normalisation, market learning, profile mapping, suitability/competitiveness separation, counterfactual upskilling with stretch→best-now promotion)
- `research_overview.md` — added press/pulse climate effects distinction (birds respond to press, possums to pulse) and its implications for monitoring and conservation
- `INDEX.md` — updated to include `positioning.md`

**Eval set expanded:**
- 100 → 130 questions (+30 new)
- New questions cover: `positioning.md` (5), `research_projects_detail.md` (9), `talks.md` (4), `publications.md` technical summaries (7), Job Intelligence Engine depth (5)
- Distribution: direct_fact 46, numerical 18, comparative 17, relationship 15, temporal 15, holistic 12, spanning 7

---

## Session 2 (2026-04-25) — Knowledge Base Enrichment

### What was built

**Enriched existing files:**
- `publications.md` — added `**Technical summary:**` to every first-author paper (data used, model/method, key decision, output) and added an *Under Review* section for the altitudinal migration manuscript
- `projects_ai_flagship.md` — added final ensemble performance metrics (MAE $29.95, R² 86.3%) and updated AI-JIE model reference to `gpt-5.4-mini`
- `research_overview.md` — added 7th key PhD contribution (altitudinal migration, under review)

**New files created:**
- `research_projects_detail.md` — 9 research project technical case studies (Problem / Approach / Stack / Results / Impact / Data links): mechanistic possum framework, altitudinal migration, community reshuffling, spatiotemporal bird models, possum population viability, SDM→abundance ML, bird trends + Shiny app, biogeochemical cascades, forest gap GLMs
- `talks.md` — all 15+ conference presentations and posters (2017–2025) in table format, with awards and key context

**Index updated:** `INDEX.md` updated to include the two new files and updated descriptions.

### Source material used
All four README files uploaded to `raw_me/` (`README.md`, `README (1).md`, `README (2).md`, `README (3).md`) plus the 9 research project case study files (`bird-elevational-migration.md`, `dynamic-community-reshuffling.md`, etc.) and all conference talk files.

---

## Session 1 (2026-04-24) — Knowledge Base and Evaluation Set

### What was built

**Knowledge base** (`data/knowledge_base/`) — 11 clean Markdown files synthesised from 55+ raw portfolio files, LinkedIn PDF, and AI CV PDF. Raw files had Jekyll front matter, liquid template logic, and redundant content stripped. Organised by topic so each file is independently retrievable:

| File | Coverage |
|---|---|
| `INDEX.md` | Master index + quick-facts for common recruiter questions |
| `identity.md` | Professional narrative, career arc, character, contact, links |
| `skills.md` | Full technical stack — AI/LLM, ML, data, statistical methods |
| `experience.md` | Complete work history with role scope and context |
| `education.md` | Degrees, certifications, courses, self-directed study |
| `projects_ai_flagship.md` | LLM Engineering Lab, AI-JIE, Job Intelligence Engine |
| `projects_skill_labs.md` | MLB SQL, Python ML/OOP/EDA skill labs |
| `research_overview.md` | PhD (tropical montane biodiversity) + postdoc (flying foxes) |
| `publications.md` | All papers: citation, lay summary, DOI link |
| `recognition.md` | Awards, grants, 15 threatened species nominations, media |
| `teaching.md` | Teaching history and student mentoring |

**Evaluation set** (`eval/tests.jsonl`) — 100 ground-truth Q&A pairs covering 7 question categories: `direct_fact` (25), `temporal` (15), `comparative` (15), `numerical` (15), `relationship` (15), `spanning` (5), `holistic` (10). All validated: JSON structure, field names, types, and category names confirmed clean.

---

## Architectural decisions

### 1. Knowledge base design: summary + links, not full content
Raw files contained 200KB+ of content with heavy redundancy (same information in the CV, LinkedIn, portfolio pages, and individual paper pages). The knowledge base consolidates to ~50KB / ~12,500 tokens, retaining:
- The information needed to answer questions directly
- Technical and lay summaries of papers and projects
- Links to primary sources (GitHub, DOIs, live apps, HuggingFace) for depth

**Rationale:** A RAG system for this use case is answering conversational questions, not reproducing documents. Links handle the "show me the full thing" case without polluting retrieval with noise.

### 2. Chunking strategy: split by heading boundaries, not fixed token count
Total corpus is ~12,500 tokens — small enough to fit in a single LLM call. But retrieval precision still requires chunking. Files like `projects_ai_flagship.md` and `publications.md` cover multiple distinct sub-topics in ~2,000 tokens each. Retrieving a full file when only one section is relevant degrades answer quality.

**Decision:** Split on `##`/`###` headings (logical sections), preserving the heading as part of the chunk. `INDEX.md` is stored as a single un-split chunk — it is designed to arrive whole for numerical/holistic queries. Starting at `###` granularity; if eval shows chunks are too small, widen to `##` only.

### 3. Web fetch: links-as-pointers, no live fetch in v1
For a personal digital twin answering known facts about a known person, live web fetch adds latency and failure modes for no benefit. The knowledge base is the authoritative source.

**Exception identified:** GitHub READMEs. The knowledge base has project summaries but not implementation-level details. A targeted fetch of specific GitHub READMEs on demand is the one addition that would meaningfully expand depth — deferred to post-v1.

### 4. Evaluation-first approach
The eval set was built before the RAG pipeline so that architectural decisions (chunking strategy, retrieval depth, prompt design) can be measured rather than guessed. Target metrics: MRR, nDCG for retrieval quality; LLM-as-judge for answer quality. The 7-category structure tests the full spectrum from single-chunk lookups to multi-file synthesis.

---

## Knowledge base gaps identified

These are known omissions at the time of the KB build:

1. **GitHub READMEs not ingested** — the flagship projects have detailed READMEs with setup instructions, architecture diagrams, and implementation notes not in the current knowledge base. A recruiter or technical user asking implementation-level questions will hit this gap.

2. **Thermoregulation research (postdoc)** — the Olivia Bond student project is summarised in `research_overview.md` and `teaching.md`, but there is no standalone document for this specific research thread, which is the most current active work.

3. **Agentic AI lab projects** — the `llm-engineering-lab.md` covers the GitHub repo, but the ongoing agentic-ai-lab work (including this digital twin) is not represented. Worth adding once there is something to say.

---

## On the GitHub README question

**Recommendation: add README summaries to the knowledge base, not raw READMEs.**

| Option | Verdict | Reason |
|---|---|---|
| Links to GitHub (current) | Good baseline | Covers "where can I see this?" but can't answer implementation questions |
| README summaries in KB | Recommended | Adds setup context, architectural notes, and implementation details without noise |
| Raw README ingest | Avoid | READMEs have badges, install instructions, code blocks — high noise for retrieval |
| Code explanation files | Avoid | Too much volume, goes stale immediately, answers questions no recruiter actually asks |

The right boundary: the knowledge base should be able to answer "how does the chunking work in the Expert Knowledge Worker project?" but not "what does line 47 of `ingest.py` do?"

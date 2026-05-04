# Digital Twin — Conversational Agent Representing Alejandro de la Fuente

**Source:** https://github.com/AlejandroFuentePinero/digital-twin

## What it is

This is the README for the very system you are interacting with. The Digital Twin is a multi-LLM conversational agent that represents Alejandro de la Fuente professionally — answering recruiter, collaborator, and technical-interviewer questions about his skills, experience, research, and projects.

It is built end-to-end as a portfolio-grade demonstration of production-AI engineering patterns: classify-then-route orchestration, Frame/Substance prompt composition (always-on profile + on-demand retrieval), branch-aware tool use with a bounded loop, multi-LLM guardrail with structured retry, deterministic short-circuits for canonical refusals, full per-turn observability logs, and ADR-driven architectural discipline. The agent itself is the most complete answer to "what kind of AI engineering does Alejandro do?".

## Architecture

A classify-then-route pipeline (per ADR-0003):

```
User question
    ↓
Classifier (gpt-4.1-nano)  — multi-label + confidence
    ↓
Branch dispatch — GAP / BEHAVIOURAL / TECHNICAL / GENERIC / LOGISTICAL
    ↓
Retrieval (ChromaDB, top-K) + Prompt composer
    ↓
Generator (gpt-4.1)  — TECHNICAL only: ToolLoop with fetch_project_readme
    ↓
Guardrail (Claude Sonnet 4.6, distinct model family) + retry loop (max 3)
    ↓
Enriched interaction log (HuggingFace Dataset in prod / local JSONL in dev)
    ↓
Sentinel (local Gradio app, on-demand)
```

Key modules in `src/`:

- **`classifier.py`** — `gpt-4.1-nano` returning `{labels, confidence}`. Sees last 2 turns + current question. Defaults to `GENERIC` on low confidence.
- **`branches.py`** — `BranchSpec` registry. Each branch declares profile sections, retrieval `final_k`, model-callable tools, and branch-specific rule keys (resolved against `rules.RULES`).
- **`composer.py`** — assembles per-branch system prompt. Same composer call for both generator and guardrail roles, so calibration cannot drift between writer and judge.
- **`rules.py`** — single source of truth for rule fragments (persona, scope, security, numerical_completeness, project_links, calibration_ladder, concise_disclosure, deflection, tool_rules).
- **`generator.py`** — `gpt-4.1` answer call. Wraps rejection-feedback into the system prompt for retry attempts.
- **`tools.py`** — `ToolRegistry` (loads `data/readmes/registry.json`, validates referenced files at startup), `build_fetch_project_readme_tool` (assembles the tool spec with `additionalProperties: false` schema lock and per-call observability callback), `make_litellm_tool_callable` (LiteLLM↔ToolLoop adapter).
- **`tool_loop.py`** — generic bounded ToolLoop. `MAX_TOOL_CALLS = 3`. Model-agnostic (takes a callable and ToolSpec list); terminates on text response.
- **`guardrail.py`** — `Claude Sonnet 4.6` evaluator. Branch-aware via the same composer. Deterministic short-circuit on the canonical gap phrase.
- **`pipeline.py`** — per-turn orchestrator. Routes generation through ToolLoop or Generator based on branch's tool field. Per-attempt tool budget reset.
- **`interaction_log.py`** — enriched per-turn record schema (branch, classifier_labels, attempts[], tool_calls[] with `attempt_index`, retrieved_chunks, latency_ms, knew_answer, contact_offered/provided).

## Key engineering decisions

- **Frame/Substance split (ADR-0001).** `data/profile.md` is the always-on Frame — sectioned by named `##` blocks loaded selectively per branch (~2–2.5k tokens). `data/knowledge_base/` is the Substance — retrieved on demand via ChromaDB. No duplicate sources of truth.
- **Classify-then-route orchestration (ADR-0003).** Five branches with distinct prompts rather than one monolithic prompt. Branch composer dedupes shared sections (e.g., `identity` loads once per turn even when multi-label).
- **Same composer for generator and guardrail.** Both roles get the same composed prompt for the same branch — wording cannot drift between what the model writes and what the guardrail judges.
- **Guardrail retry loop with structured feedback.** Up to `MAX_ATTEMPTS = 3`; rejection feedback wraps into the next attempt's system prompt. Canned-refusal floor if all attempts fail.
- **Deterministic short-circuit on the gap phrase.** When a generated answer equals the canonical "I don't have that information in my knowledge base." string, guardrail returns acceptable without an LLM call (`guardrail_ms = 0`).
- **TECHNICAL branch with bounded tool loop.** Only branch with model-callable tools. `fetch_project_readme(project)` returns distilled README content for one of 24 catalogued projects/papers from a tool-only collection in `data/readmes/` (not in the KB — clean separation between retrieval surface and tool surface). Schema locked with `additionalProperties: false` for defence-in-depth.
- **Distinct model families for generator and guardrail.** OpenAI and Anthropic respectively — reduces shared failure modes (e.g., shared training-data biases or prompt-injection susceptibilities).
- **Living LIMITATIONS register.** `docs/LIMITATIONS.md` tracks observed and predicted system-wide limitations with explicit trip-wire conditions per entry — operational discipline rather than aspiration.
- **ADR-driven architectural decisions** (`docs/adr/`). Every load-bearing structural choice is documented as an ADR with context, decision, consequences. Decisions are themselves treated as working hypotheses revisable on signal.

## Stack and discipline

- **Python 3.12** managed with `uv` (no venv activation).
- **LLMs:** `gpt-4.1` (generator), `gpt-4.1-nano` (classifier + retrieval rewrite/rerank), `Claude Sonnet 4.6` (guardrail). Provider-agnostic via LiteLLM.
- **RAG:** ChromaDB with hierarchical chunking (LLM-generated headlines + summaries + verbatim source), query rewriting, dual retrieval pass merge, LLM reranking. v3 retrieval baseline: MRR 0.868, nDCG 0.838, coverage 89%.
- **Eval:** `eval/run_eval.py` over 149 Q&A pairs across 7 categories (direct_fact, temporal, comparative, numerical, relationship, spanning, holistic). Retrieval (MRR, nDCG, coverage) + LLM-as-judge answer scoring (accuracy, completeness, relevance 1–5). v4 routed-pipeline baseline: MRR 0.866, nDCG 0.864, accuracy 4.56/5, completeness 4.64/5, gap rate 0.0%.
- **Test discipline (`docs/TESTING.md`):** matching `test_<module>.py` per src module, mock at boundaries only (no LLM API calls in pytest), `module_health.py` dashboard for coverage gaps. 175+ behaviour tests covering routing, composition, retry, deflection, tool loop, guardrail short-circuit.
- **Observability:** every turn writes a structured JSONL log record with full attempt history, retrieved chunk references, per-stage latencies, and tool_calls with attempt_index attribution. Sentinel (Phase 4) reads the log for failure-mode aggregation.

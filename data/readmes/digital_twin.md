# Digital Twin — Conversational Agent Representing Alejandro de la Fuente

**Source:** https://github.com/AlejandroFuentePinero/digital-twin
**Live app:** https://alejandrofupi-digital-twin.hf.space

## What it is

A multi-LLM conversational agent that answers professional questions about Alejandro de la Fuente — research, projects, skills, trajectory — grounded in a curated knowledge base, with deflection to a polite redirect when the question is out of scope rather than hallucination. Embedded on the home page of `alejandrofuentepinero.github.io`; deployed on HuggingFace Spaces.

The deliberate framing: a single-prompt chatbot gives every recruiter the same surface, regardless of whether they're probing a real gap (AWS depth, deserves an honest acknowledgement and the active-learning context), asking how a flagship project chunks documents (technical depth, deserves tool-fetched README content), or asking about behavioural patterns (deserves a concrete story, not platitudes). Routing the question to a branch with the right prompt and the right tool surface is the architectural difference between a chatbot wrapper and a system. The agent's calibration on gaps, refusal posture, and retrieval transparency are answers in themselves.

## Architecture

A classify-then-route pipeline (see [ADR-0003](https://github.com/AlejandroFuentePinero/digital-twin/blob/main/docs/adr/0003-classify-then-route-orchestration.md)). One question, five concrete stages, each with its own model and prompt.

### 1. Classifier
`gpt-4.1-nano` returns `{labels, confidence}`. Sees the last 2 conversation turns plus the current question. Defaults to `GENERIC` on low confidence; multi-label allowed up to 2 labels. ~$0.0001 per call, ~200–400 ms added per turn.

### 2. Branch composer
Selects from five branches: `GAP`, `BEHAVIOURAL`, `TECHNICAL`, `GENERIC`, `LOGISTICAL`. Each branch declares which `profile.md` sections to load (identity, gap_inventory, personal_stories, etc.) and which rules apply (calibration ladder, deflection, tool access). Sections and rules dereference shared constants, so the **same composer call drives both the generator and the guardrail** — eliminating the most common cause of guardrail-loops in retry pipelines, where writer and judge run on subtly different specs.

### 3. Retrieval
ChromaDB top-6 against an LLM-enriched chunk store: each chunk embeds `headline + summary + verbatim source` as one vector, so query phrasing has multiple match surfaces. Four-stage retrieval: query rewriting → dual retrieval pass (original + rewritten) → chunk merge → LLM rerank to final-k.

### 4. Generator
`gpt-4.1` produces the answer. The `GENERIC`, `GAP`, and `TECHNICAL` branches each enter a bounded tool loop (`MAX_TOOL_CALLS = 3`) with `fetch_project_readme` for one of 28 distilled project / paper docs. The tool's argument is a `Literal[*REGISTRY.keys()]` pinned to the known project keys at startup; misconfiguration fails at import, not on first user turn. `LOGISTICAL` and `BEHAVIOURAL` are tool-free.

### 5. Guardrail
`Claude Sonnet 4.6` — a model from a different family — judges the answer against the same composed prompt the generator saw. Up to 3 retries with structured rejection feedback wrapped into the next attempt's system prompt; falls back to a polite canned-refusal floor if all attempts fail.

Each turn writes one enriched JSONL record (branch, classifier confidence, retrieval chunks with section headings, tool calls with attempt-index attribution, retry attempts each with guardrail feedback, per-stage latency, contact-flow state) to a HuggingFace Dataset in production. Sentinel reads this log directly — no derived metrics tables, no eventually-consistent summaries.

Frame-vs-Substance separation is load-bearing (see [ADR-0001](https://github.com/AlejandroFuentePinero/digital-twin/blob/main/docs/adr/0001-always-on-profile-and-kb-as-depth.md)): a small ~2k-token profile is always on (loaded selectively per branch); the larger knowledge base is retrieved on demand. No duplicate sources of truth.

## Key engineering decisions

- **Routing instead of one prompt.** A monolithic always-on prompt that loads profile + all rules + retrieval lands at ~6–7k tokens and dilutes attention on cheaper models. Branch routing avoids the bloat. A model-driven alternative — let the model decide what context to fetch via tools — was rejected for v1 because cheap classifiers proved unreliable at tool selection.

- **Same composer drives the generator AND the guardrail.** Both calls assemble their system prompt from the same code path against the same branch and rule set. Wording cannot drift between what the model is asked to write and what the judge is asked to evaluate against — structurally, not by convention.

- **Distinct model families for generator and guardrail.** OpenAI for generation, Anthropic for the guardrail. Shared training data and shared prompt-injection susceptibilities are real risks when both come from the same family — splitting families reduces shared failure modes at no architectural cost.

- **Tool access scoped, not maximal.** `fetch_project_readme` is wired into `GENERIC`, `GAP`, and `TECHNICAL` — the three branches whose questions can land on a named project. `LOGISTICAL` and `BEHAVIOURAL` are deliberately tool-free; their question shapes don't surface project depth, so handing them a tool would only be a fabrication vector. The model can't invent a tool where it isn't wired, and the guardrail can't reject a tool-grounded answer for "fabrication" because the tool surface is whitelisted. The original design (Session 12 ADR-0003) gated tool access to `TECHNICAL` only; widening to `GENERIC`/`GAP` (Session 56) was empirical — recruiters phrase "what is AI-JIE?" as GENERIC and "do you have RAG experience?" as GAP, and starving those branches of the tool produced gap-phrase responses on questions where the README content already existed.

- **Outcome-based canary contract, not mechanism-based.** A 50-question canary corpus replays through the pipeline on operator cadence; the drift detector flags `branch_changed`, `event_type_changed`, `outcome_changed`, `keyword_coverage_dropped`, `red_flag_emerged`, `latency_p95_regression`. It deliberately does NOT flag retrieved-chunk-set or retry-depth deltas — those mechanism signals fire on every legitimate KB rebuild and add noise without adding signal. Drift means *"did the system stop doing what we wanted"*, not *"did it do it differently"*.

## Stack and discipline

Python 3.12 managed with `uv`. LiteLLM for provider-agnostic LLM access. ChromaDB for retrieval. Gradio for the chat surface and the Sentinel observability dashboard. Pydantic for record schemas. Tenacity for retry on transient provider errors. Deployed to HuggingFace Spaces (`cpu-basic`, free tier); both interaction logs and contact-form submissions persist durably to a private HuggingFace Dataset (buffered writer with size-or-time flush, SIGTERM-safe drain on container shutdown, crash-recovery flush on restart).

Test discipline (`docs/TESTING.md`): matching `tests/test_<module>.py` per source module, mock at I/O boundaries only (no LLM API calls in pytest). 620+ behaviour tests covering routing, composition, retry, deflection, tool loop, guardrail short-circuit, log buffering, schema migration, drift detection. Eval baseline (v4, post-redesign, in-process against the routed pipeline): MRR 0.866, nDCG 0.864, accuracy 4.56/5, completeness 4.64/5, gap rate 0.0% across 149 questions in 7 categories. Per-turn latency on free-tier `cpu-basic`: p50 ≈ 12.7 s, p95 ≈ 17.3 s, dominated by the four LLM round-trips per turn. 11-step deployed-Space smoke test passed across all five branches end-to-end.

Sentinel (the observability dashboard): 14 metrics across Outcome / Routing / Engagement / Tool use / Latency blocks, per-branch trends, failure feed with replay-into-current-pipeline, KB coverage tracking, weekly LLM-batched gap clusters and deflection summaries, and the canary drift trajectory tracking against a frozen baseline. Every load-bearing structural choice has an ADR in `docs/adr/`; observed and predicted system limits live in `docs/LIMITATIONS.md` with explicit trip-wire conditions per entry — decisions are treated as working hypotheses, limitations as data, not aspiration.

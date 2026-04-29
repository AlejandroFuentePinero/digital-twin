# Digital Twin — TODO

Active task list for the post-redesign rebuild. Updated each session.
For the canonical glossary see [`CONTEXT.md`](../../../CONTEXT.md). For architectural decisions see [`docs/adr/`](../../../docs/adr/). For session history see `DECISIONS.md`. `PLAN.md` and `ARCHITECTURE.md` are pre-redesign and partially superseded.

**Last updated:** 2026-04-29
**Current phase:** Phase 1 (Profile + KB content rewrites) — ready to start

---

## Pre-redesign baseline (v3)

The system that exists in the codebase today predates the 2026-04-29 redesign. Eval baseline:
- MRR: 0.868 / nDCG: 0.838 / coverage: 89%
- Answer accuracy 4.46 / completeness 4.30 / relevance 4.66 / gap rate 0.7%
- Weaknesses: temporal MRR 0.783, numerical completeness 3.94/5

Per the persistent feedback memory (`feedback_redesign_over_patching.md`), the answer/guardrail/logger/app modules are rewritten — not patched — in Phase 2. `ingest.py`, the KB structure, and the eval pipeline are built on.

---

## Phase 1 — Profile + KB content rewrites

Content-only phase. No code changes. Sets up the **Frame** (loaded by branches in Phase 2) and addresses the two KB-structure weaknesses identified in v3 eval.

- [ ] Write `projects/digital-twin/data/profile.md` (~2,000–2,500 tokens), structured as named `##` sections:
  - [ ] `## identity` (~150 tokens) — one-paragraph identity block
  - [ ] `## narrative_summary` (~500 tokens) — career arc, what he does, how he frames himself
  - [ ] `## transfer_principles` (~400 tokens) — 5 transfer mechanisms, prose-only (no parallels table; that stays in `positioning.md`)
  - [ ] `## gap_inventory` (~500 tokens) — 5–7 known gaps with broader skill, exposure level, active learning specifics, KB cross-reference
  - [ ] `## logistics` (~200 tokens) — location, availability, languages, how to discuss salary
  - [ ] `## personal_stories` (~400 tokens, **placeholder until Phase 5**) — 1–2 STAR-format anecdotes; only added when Alejandro confirms the wording
- [ ] Rewrite `data/knowledge_base/positioning.md` — remove transfer-principle prose that moves to `profile.md`. Keep parallels table, worked examples, "what he doesn't bring."
- [ ] Add `## Career Timeline` section to `data/knowledge_base/experience.md` — explicit start/end years per role so chunk headlines surface dates. Fixes temporal retrieval (v3 MRR 0.783).
- [ ] Re-ingest KB. `profile.md` is naturally skipped (lives outside `data/knowledge_base/`). Verify chunk count and category distribution.
- [ ] Sample-check chunks via `sample_chunks.py` — confirm temporal chunks now have dates in headlines.

Phase 1 deliverable: `profile.md` is content-complete (minus `personal_stories`), KB rewrites are merged, ChromaDB is re-ingested. No code changes.

---

## Phase 2 — Routing + new pipeline (rewrites)

Per ADR-0003. The current `answer.py`, `guardrail.py`, and `logger.py` are replaced. New modules added for the classifier and branch dispatch.

### Rewrites
- [ ] **`logger.py`** — new enriched record schema:
  ```
  timestamp, session_id, turn_index, question, event_type, branch, classification_confidence,
  attempts: [{answer, is_acceptable, guardrail_feedback}],
  retrieved_chunks: [{source_file, section_heading}],
  tool_calls: [{name, args, status}],
  latency_ms: {classifier, retrieval, generation, guardrail, total},
  knew_answer, contact_offered, contact_provided
  ```
  Old `data/logs/interactions.jsonl` is nuked (dev-only data).
- [ ] **`answer.py`** — replaced. New control flow: classifier → branch dispatch → generator (with tool loop in TECHNICAL) → guardrail → log. Composed-from-constants prompt pattern (Q11 (C)).
- [ ] **`guardrail.py`** — replaced. Branch-aware rules. Calibration ladder, deflection rule, scope, and security rules imported from shared constants used by both `answer.py` and `guardrail.py` (drift prevention).

### New modules
- [ ] `classifier.py` — cheap classifier (`gpt-4.1-nano`) returning `{labels, confidence}`; sees last 2 turns + current question; defaults to GENERIC on low confidence.
- [ ] Branch composers (one module or `src/branches/`) — one named function per branch (GAP, BEHAVIOURAL, TECHNICAL, GENERIC, LOGISTICAL). Each composes its system prompt from shared constants + selected `profile.md` sections + retrieval results.
- [ ] `LogReader` abstraction — `LocalReader` (JSONL) + `HFReader` (placeholder, real impl in Phase 6). Used by Sentinel.
- [ ] `tools/fetch_project_readme.py` — registry-driven tool with `Literal[*REGISTRY.keys()]` enum.
- [ ] `data/readmes/registry.json` + 5–8 cached project READMEs.

### Universal rules (loaded in every branch)
- [ ] Persona block.
- [ ] Scope (in/out) — inherits from current `SYSTEM_PROMPT` content, refined.
- [ ] Security / injection-defence — universal; never per-branch.
- [ ] Numerical-completeness rule: *"For numerical questions, include specific numbers from the context — don't paraphrase quantities away."*

### Tests
- [ ] `tests/test_classifier.py` (new) — confidence behaviour, history-aware disambiguation, multi-label, default-to-GENERIC.
- [ ] `tests/test_branches.py` (new) — per-branch composition correctness; section selection.
- [ ] `tests/test_readme_registry.py` (new) — registry/disk drift detection.
- [ ] `tests/test_answer.py` (rebuild) — full routed pipeline integration; existing tests are tied to `answer_with_guardrail`'s monolithic shape and become stale.
- [ ] `tests/test_guardrail.py` (rebuild) — branch-aware evaluation.
- [ ] `tests/test_logger.py` (rebuild) — enriched schema, all event types.
- [ ] `tests/test_eval.py` (build on; surgical updates) — metric tests (`_reciprocal_rank`, `_dcg`, `_ndcg`, `_mean`, aggregation, versioning, `load_tests`) are pure functions that survive intact. The single `eval_retrieval` integration test updates to pass a branch label.
- [ ] `tests/test_ingest.py` (survives unchanged).

### `app.py` updates (build on existing scaffold)
The current `app.py` already has: UUID `session_id`, Gradio `gr.State` for session/history, history truncation to last 10 turns, chat-input + new-conversation button, avatar. Additions only:
- [ ] Per-session state: `turn_counter`, `contact_provided` flag (alongside existing `session_id` and `history`).
- [ ] Periodic invitation hook at turn 3 (single-fire), suppressed when `contact_provided=True`.
- [ ] `log_user_details` form affordance: collapsible row at the bottom of the chat, persistently visible after first invitation. On submit, write a record stamped with `session_id`, `turn_index`, `timestamp`, and the form fields, so the submission can be joined back to the enriched interaction log on `session_id` to reconstruct the conversation that led to the contact request.
- [ ] `new_session()` resets the new flags too.
- [ ] Wire to the routed `answer` entry point (was `answer_with_guardrail`).

---

## Phase 3 — Re-eval baseline (v4)

Build on the existing eval pipeline; the metric and aggregation code is reused. The interface change is real but contained.

- [ ] Update `eval/run_eval.py`:
  - [ ] `eval_retrieval` classifies each question first, then calls a branch-aware retrieval (`fetch_context_for_branch(question, branch)`). The classifier becomes a confounder in retrieval metrics — note this in `notes`.
  - [ ] `eval_answer` calls the routed `answer` entry point (still no guardrail in eval — Session 9 decision: raw answer quality is the cleaner signal).
  - [ ] Per-question record gains: `branch`, `classification_confidence`, optional secondary label.
  - [ ] Result aggregation gains: `by_branch` (mirroring `by_category`) and a `category × branch` cross-tab so we can see how branches handle different question categories.
- [ ] `eval/plot_eval.py` survives as-is. Schema additions are optional fields it'll ignore.
- [ ] Run on the existing 149 questions only — no new categories yet.
- [ ] Commit `v4_*.json`. Note in `notes` that v3 → v4 has comparability caveats (routing reshapes retrieval).
- [ ] Compare: targets MRR/nDCG ≥ v3, accuracy ≥ v3, gap rate ≤ v3.

---

## Phase 4 — Sentinel + LLM failure summaries

- [ ] `src/sentinel.py` — local Gradio app, 5 panels + 3-flag panel:
  1. Health overview (today / 7d / 30d)
  2. Trend chart
  3. Failure feed (recent unacceptable answers, all attempts, feedback)
  4. Gap clusters
  5. Deflection feed
- [ ] `cluster_gaps.py` — weekly batch script; clusters gap-phrase questions with LLM labels; writes `data/logs/gap_clusters.json`.
- [ ] `summarize_failures.py` — three weekly LLM passes, one per failure-mode group (unacceptable, deflection, gap). Output cached as Markdown reports under `data/logs/summaries/`.
- [ ] Sentinel reads precomputed cluster/summary files (no live LLM calls in dashboard).

---

## Phase 5 — Break the live system

- [ ] Local probe session — try recruiter probes, behavioural questions, gap questions, edge cases.
- [ ] Identify actual failure modes (informed by Sentinel signals when log is non-trivial).
- [ ] Add 1–2 STAR-format stories to `profile.md`'s `personal_stories` section — only ones Alejandro would say verbatim live.
- [ ] Add ≤10 KB-grounded recruiter eval questions (only after corresponding KB content exists). Run v5 eval.

---

## Phase 6 — HF Dataset migration

- [ ] Implement `HFReader` and `HFWriter` in `LogReader` abstraction.
- [ ] Buffered append: local JSONL buffer, batch flush every N writes or M minutes.
- [ ] Schema versioning: `schema_version` field on every record; reader handles version skew.
- [ ] HF write token in Space secrets; rotation procedure documented.
- [ ] Sentinel auto-detects backend (HF token present → HFReader; else LocalReader).

---

## Phase 7 — Deploy to HuggingFace Spaces

- [ ] Package `app.py` for HF Spaces.
- [ ] Configure Space secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `HF_WRITE_TOKEN`.
- [ ] Smoke test: classifier, all 5 branches, guardrail+retry, log writes, deflection, periodic invitation, contact form.
- [ ] Latency baseline check (p50/p95).
- [ ] Link Space from portfolio.

---

## Open implementation details (not blocking architecture)

- Final phrasing for: deflection rule, periodic-invitation closing line, contact-form copy.
- Selection of 5–8 flagship project READMEs to cache in `data/readmes/`.
- Formal test plan (one document covering all phases — written when test surface is concrete).
- Gradio UI polish: welcome message, theme, mobile responsiveness.

---

## Three ground rules (governance)

1. **The bar for putting content in the agent's mouth is "would Alejandro say this verbatim to a recruiter on a phone call?"** — content lands on observed failure, not speculation.
2. **Frame is loaded by branch; Substance is retrieved.** No duplicate sources of truth.
3. **Eval questions must be KB-grounded.** Adding eval before content measures absence.

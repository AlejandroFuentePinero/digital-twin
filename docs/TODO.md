# Digital Twin — TODO

Active task list for the post-redesign rebuild. Updated each session.
For the canonical glossary see [`CONTEXT.md`](../CONTEXT.md). For architectural decisions see [`adr/`](./adr/). For session history see `DECISIONS.md`. `PLAN.md` and `ARCHITECTURE.md` are pre-redesign and partially superseded.

**Last updated:** 2026-05-03 (Session 24)
**Current phase:** Phase 2 — **branch surface complete; Phase 2 itself still has `#16` (contact form) outstanding.** All five branches wired (GENERIC + GAP + LOGISTICAL + BEHAVIOURAL + TECHNICAL). Issues closed: `#13`, `#14`, `#15` (foundation + GAP), `#21` + `#26` (R1 + R2 smoke-tests), `#22` + `#24` + `#25` (polish), `#19` (LOGISTICAL branch), `#17` (BEHAVIOURAL branch + deflection rule + Story 8), `#18` (TECHNICAL branch + ToolRegistry + ToolLoop + 24 distilled docs), `#20` (LIMITATIONS.md register). The routed pipeline is live with all five branches; real `gpt-4.1-nano` classifier; multi-label routing; 5-layer active-learning defense; deterministic guardrail short-circuit on the canonical refusal phrase; soft conciseness nudge cross-branch; honest deflection on behavioural off-list questions; bounded tool loop with `fetch_project_readme` over a 24-key registry on TECHNICAL turns; guardrail receives tool-fetched content via per-attempt judge-prompt recomposition (`LIMITATIONS::R1` fix). KB date-stable past 2026-05-13. Standing concerns logged in [`docs/LIMITATIONS.md`](./LIMITATIONS.md) (5 observed + 8 predicted + 1 resolved entries with explicit trip-wires). **Next (Phase 2 closeout): `#16`** (contact form + per-session `contact_provided` flag + periodic invitation hook + `log_user_details` form affordance — the last `app.py` work item from the original Phase 2 plan). After `#16` lands, Phase 2 closes and **Phase 3 / `#2`** (v4 eval baseline — already unblocked) opens. Test count 177/177; KB at 104 chunks (positioning.md prose pruned in #18 as the last Phase 1 sub-task). Phase 1 **complete**.

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

- [x] Write `data/profile.md` (~3,000 tokens, slightly over the original ~2,000–2,500 estimate; see deviations below), structured as named `##` sections:
  - [x] `## identity` (~150 tokens) — one-paragraph identity block.
  - [x] `## narrative_summary` (~580 tokens) — career arc, what he does, how he frames himself.
  - [x] `## transfer_principles` (~430 tokens) — **6** transfer mechanisms, prose-only. Expanded from the planned 5 to add "Critical evaluation of novel work — the AI governance instinct" (peer-review-as-judgment-without-benchmarks → AI eval/alignment).
  - [x] `## gap_inventory` (~630 tokens) — **5** gaps in the canonical CONTEXT.md Gap-aware response shape: specific gap with **calibration-ladder** exposure rung + **Broader skill** with named KB-verifiable evidence + **Active learning** with concrete credentials and status. Industry experience, DevOps, cloud, frontend, deep learning. Officeworks AI engineer offer (start 13 May 2026) closes the industry-experience gap structurally.
  - [x] `## logistics` (~195 tokens) — Melbourne, AU PR full work rights, Officeworks AI engineer 13 May 2026 (hybrid), industry exclusions, comp/travel opt-out, Officeworks-confidentiality redirect.
  - [x] `## personal_stories` (~980 tokens) — **pulled forward from Phase 5 to Phase 1.** Seven recruiter-bar stories with explicit routing table. Story 6 (origin — grandmother and rural Spain) gated to surface only on "tell me something not in your CV that defines you" / "what drives you" prompts. Override of the Phase 5 deferral was Alejandro's call: the work is done at recruiter-bar, no benefit to delaying.
- [ ] Rewrite `data/knowledge_base/positioning.md` — remove transfer-principle prose that moves to `profile.md`. Keep parallels table, worked examples, "what he doesn't bring."
- [ ] Add `## Career Timeline` section to `data/knowledge_base/experience.md` — explicit start/end years per role so chunk headlines surface dates. Fixes temporal retrieval (v3 MRR 0.783).
- [ ] Re-ingest KB. `profile.md` is naturally skipped (lives outside `data/knowledge_base/`). Verify chunk count and category distribution.
- [ ] Sample-check chunks via `sample_chunks.py` — confirm temporal chunks now have dates in headlines.

Phase 1 deliverable: `profile.md` is content-complete (**including** `personal_stories` — pulled forward from Phase 5), KB rewrites are merged, ChromaDB is re-ingested. No code changes.

---

## Phase 2 — Routing + new pipeline (rewrites)

Per ADR-0003. The current `answer.py`, `guardrail.py`, and `logger.py` are replaced. New modules added for the classifier and branch dispatch.

### Rewrites
- [x] **`logger.py`** — new enriched record schema:
  ```
  timestamp, session_id, turn_index, question, event_type, branch, classification_confidence,
  attempts: [{answer, is_acceptable, guardrail_feedback}],
  retrieved_chunks: [{source_file, section_heading}],
  tool_calls: [{name, args, status}],
  latency_ms: {classifier, retrieval, generation, guardrail, total},
  knew_answer, contact_offered, contact_provided
  ```
  Old `data/logs/interactions.jsonl` is nuked (dev-only data).
- [x] **`answer.py`** — replaced (deleted). Control flow lives in `pipeline.py`: classifier → branch dispatch → generator (with tool loop in TECHNICAL — pending issue #18) → guardrail → log. Composed-from-constants prompt pattern via `composer.py` + `rules.py`.
- [x] **`guardrail.py`** — replaced. Branch-aware via composed system prompt. Universal rules (persona/scope/security/numerical_completeness) imported by both `composer.py` (used by generator) and `guardrail.py` indirectly through the same composer call — drift prevention. Old monolithic `evaluate()` and `SYSTEM_PROMPT` shim removed at step 10. **Branch-specific** rules (calibration_ladder / deflection_rule / tool_rules) land with their branches: issues #15 / #17 / #18.

### New modules
- [ ] `classifier.py` — cheap classifier (`gpt-4.1-nano`) returning `{labels, confidence}`; sees last 2 turns + current question; defaults to GENERIC on low confidence.
- [ ] Branch composers (one module or `src/branches/`) — one named function per branch (GAP, BEHAVIOURAL, TECHNICAL, GENERIC, LOGISTICAL). Each composes its system prompt from shared constants + selected `profile.md` sections + retrieval results.
- [ ] `LogReader` abstraction — `LocalReader` (JSONL) + `HFReader` (placeholder, real impl in Phase 6). Used by Sentinel.
- [ ] `tools/fetch_project_readme.py` — registry-driven tool with `Literal[*REGISTRY.keys()]` enum.
- [ ] `data/readmes/registry.json` + 5–8 cached project READMEs.

### Universal rules (loaded in every branch)
- [x] Persona block.
- [x] Scope (in/out) — inherits from current `SYSTEM_PROMPT` content, refined.
- [x] Security / injection-defence — universal; never per-branch.
- [x] Numerical-completeness rule: *"For numerical questions, include specific numbers from the context — don't paraphrase quantities away."*

### Tests

All new and rebuilt test files follow the convention in [`TESTING.md`](./TESTING.md): matching `tests/test_<module>.py`, mock only at I/O boundaries, no LLM API calls. New `test_*.py` files appear in the `module_health` dashboard automatically.

- [ ] `tests/test_classifier.py` (new) — confidence behaviour, history-aware disambiguation, multi-label, default-to-GENERIC.
- [ ] `tests/test_branches.py` (new) — per-branch composition correctness; section selection.
- [ ] `tests/test_readme_registry.py` (new) — registry/disk drift detection.
- [ ] `tests/test_answer.py` (rebuild) — full routed pipeline integration; existing tests are tied to `answer_with_guardrail`'s monolithic shape and become stale.
- [ ] `tests/test_guardrail.py` (rebuild) — branch-aware evaluation.
- [ ] `tests/test_logger.py` (rebuild) — enriched schema, all event types.
- [x] `tests/test_eval.py` (build on; surgical updates) — pure-function metric tests (`_reciprocal_rank`, `_dcg`, `_ndcg`, `_mean`, aggregation, versioning, `load_tests`) survive intact. Step 10 flipped `run_eval.py`'s import from `answer` to `retrieval`+`pipeline`. The branch-label integration update to `eval_retrieval` lands with the v4 eval rewrite (Phase 3 / issue #2).
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
- **Replace [`data/readmes/digital_twin.md`](../data/readmes/digital_twin.md) with Alejandro-authored version.** Currently a Claude-authored placeholder distilled from `CLAUDE.md` + `docs/adr/` + a direct read of `src/`. Architecturally accurate but not in Alejandro's voice. The self-reference doc is the one TECHNICAL recruiters most likely to drill into ("how does this very chatbot work?"), so voice and emphasis matter. Keep the locked Q11 shape (Source link → What it is → Architecture → Key engineering decisions → Stack and discipline) when replacing. Two release-blocking gates in [`RELEASE_CHECKLIST.md::Portfolio / external`](./RELEASE_CHECKLIST.md): (1) content replacement, (2) Source link resolution (the `AlejandroFuentePinero/digital-twin` repo is currently private — the GitHub Source link returns 404 for unauthenticated visitors; either make the repo public or redirect the Source line to a public resource).

---

## Three ground rules (governance)

1. **The bar for putting content in the agent's mouth is "would Alejandro say this verbatim to a recruiter on a phone call?"** — content lands on observed failure, not speculation.
2. **Frame is loaded by branch; Substance is retrieved.** No duplicate sources of truth.
3. **Eval questions must be KB-grounded.** Adding eval before content measures absence.

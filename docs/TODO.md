# Digital Twin — TODO

Active task list for the post-redesign rebuild. Updated each session.
For the canonical glossary see [`CONTEXT.md`](../CONTEXT.md). For architectural decisions see [`adr/`](./adr/). For session history see `DECISIONS.md`. `PLAN.md` and `ARCHITECTURE.md` are pre-redesign and partially superseded.

**Last updated:** 2026-05-07 (Session 63 — **Phase 7 slice 2 (`#52`) shipped; Phase 7 closed**. Project enters observe-mode. Iframe embed live on `alejandrofuentepinero.github.io`; parent-PRD step 12 embedded smoke test passed (tool call fired on live Space, status success). Digital-twin self-reference content shipped: `data/readmes/digital_twin.md` rewrite + new `## Digital Twin` section in `data/knowledge_base/projects_ai_flagship.md`. `AlejandroFuentePinero/digital-twin` repo confirmed PUBLIC; Source links resolve. Drift detector cleanup landed mid-session (52 → 12 flags same data). Documentation consistency pass: SUMMARY.md / pipeline_diagram.mmd / CONTEXT.md / SENTINEL.md / CLAUDE.md / TESTING.md all reconciled to current state. Issues `#52` and `#6` (parent Phase 7 PRD) closed. Suite at **620 passing**.)
**Current phase:** **Observe-mode**. All seven architecture phases done. No active engineering work scheduled. Re-engage on (a) real-recruiter traffic surfacing a new failure mode, (b) content updates, or (c) canary trajectory drift worth investigating. Suite at **620 passing**.

**Locked next-step order:**
1. **Phase 6 — HF Dataset migration** (issue `#5`). `LogReader.HFReader` / `LogWriter.HFWriter` implementation; buffered append; schema versioning carry-through; HF token in env / Spaces secrets.
2. **Phase 7 — HF Spaces deploy** (issue `#6`). Package `app.py`, configure secrets, smoke-test all 5 branches + tool fires + contact form, embed Space iframe on portfolio site.
3. **Iterate from real-recruiter traffic.** Both Phase 5 watch-items (`P8` initial-drill firing + `O8` cross-branch guardrail) resolve into fix-candidate-or-accept once production traffic accumulates ~1 month of data.
4. **Tier B band tuning** (7%/15% placeholders) — recalibrate after a month of post-deploy traffic.

**Deferred (gated on Phase 5 trip-wires):**
- **Producer-rule v2** (`LIMITATIONS::P17`) — branch-identity-canonical conflation surfaced by Session 55 freeze. Defer until Phase 5 traffic shows the cost. New PRD if/when a trip-wire fires.
- **Reproducibility provenance surface** (`LIMITATIONS::P16`) — `model_id` / `temperature` / `prompt_hash` are write-only; ship the failure-drilldown surface only when an incident actually reaches for them.
- **HuggingFace Dataset migration** (issue `#5`, Phase 6) — sequenced after Phase 5.
- **HuggingFace Spaces deploy** (issue `#6`, Phase 7) — sequenced last.

**Audit-first discipline (slices 1–4):** every slice ships with a written audit at `docs/audits/slice-<N>-<name>.md` listing field readers, predicted behaviour change, fixtures requiring updates, and workarounds removed. Audit lands first; code change lands second; PR review verifies the change matches the audit.

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

## Phase 3 — Re-eval baseline (v4)  ✅ complete (Session 27)

Build on the existing eval pipeline; the metric and aggregation code is reused. The interface change is real but contained.

- [x] Update `eval/run_eval.py`:
  - [x] `eval_retrieval` classifies each question first, then calls branch-aware retrieval (uses each `BranchSpec.final_k` slice). Classifier-in-loop noted in result-file `notes`.
  - [x] `eval_answer` calls the routed pipeline's raw answer path (no guardrail per Session 9). TECHNICAL branch goes through `tool_loop` so README-grounded answers are exercised.
  - [x] Per-question record gains: `branch`, `classification_confidence`, `secondary_branch`.
  - [x] Aggregation gains: `summary.by_branch`, `cross_tab` (category × branch, sparse), `summary.classifier_low_confidence_count`. Architecture snapshot now records the full branches dict + `classifier_model` + `routing_in_loop=true`.
  - [x] One classifier call per question, shared between retrieval scoring and answer generation (avoids per-stage routing drift on borderline questions).
- [x] `eval/plot_eval.py` survives as-is — verified against the v4-shaped result file; new fields ignored gracefully.
- [x] Run on the existing 149 questions only — no new categories yet.
- [x] Committed `v4_2026-05-03.json` with comparability-caveat in `notes`.
- [x] Compare vs v3: **retrieval MRR 0.866 (≈ 0.868), nDCG 0.864 (+0.010), accuracy 4.56 (+0.10), completeness 4.64 (+0.13), gap rate 0.0% (-0.7pp).** Targets met or exceeded across the board.

Follow-up surfaced from v4 (separate issue, not this PRD): citation-scope-creep failure mode in temporal questions — the v4 generator fabricates DOIs/volumes/pages when answering "when was paper X published?" Logged in `LIMITATIONS::P11`. Ticket up next.

---

## Phase 4 — Sentinel observability layer

Restructured (Session 28) around the **9 failure modes** Sentinel exists to detect: fabrication, mis-routing, tool non-uptake, unfair gap, engagement collapse, contact-form failure, latency regression, guardrail loops, repeat failure. Plus 3 orientation signals: volume, branch mix, multi-label routing.

GitHub Issues are the source of truth for slice-level scope; this list is a checklist of execution order.

- [x] `#28` — `src/log_reader.py` (typed `LocalReader` + `HFReader` Phase-6 stub).
- [x] `#29` — `src/sentinel.py` skeleton + `src/dashboard_model.py` + Panel 1 v1 (Health Overview).
- [x] `#37` — **Prerequisite.** `InteractionRecord` schema additions (`prompt_hash` / `model_id` / `git_sha` / `temperature`) for replay + deployment markers.
- [x] `#35` — Panel 1 v2: 14 metrics across Outcome / Routing / Engagement / Tool use / Latency blocks (incl. `confident_failure_rate`, `dropoff_by_turn`, `multi_label_rate`).
- [x] `#36` — Per-metric thresholds + WoW deltas + `docs/SENTINEL.md` (proxy caveats, runbooks, low-N notes, definitional precision).
- [x] `#30` — Trend Explorer: small-multiples grid (every metric, organised by Panel 1 blocks) + click-to-zoom investigate mode (7d / 30d / 90d / All-time + prior-period comparison + flag annotations).
- [x] `#31` — Failure Feed: filterable (branch / failure-mode / window / question search) + per-session conversation view.
- [x] `#38` — Replay: button in Failure Feed → re-run record through current pipeline → side-by-side diff.
- [x] `#32` — `src/cluster_gaps.py` weekly LLM batch + Cluster panel.
- [x] `#33` — `src/summarize_failures.py` weekly LLM batch (unacceptable / deflection / gap) + Deflection panel.
- [x] `#34` — Flags panel + `FlagDetector` (`gap_rate_jump` / `new_cluster` / `repeat_failure`).

Sentinel reads precomputed cluster/summary files — no live LLM calls in the dashboard hot path.

### Phase 4.5 polish (Sessions 40–41)

Two-session arc: Session 40 added 5 load-bearing metric surfaces + published the canary PRD; Session 41 redesigned Trends from line charts to grouped bars + iterated UX based on operator feedback + ran an honest over-engineering audit.

**Session 40 (load-bearing additions):**
- [x] **Glossary** at the bottom of the Metrics tab (collapsed) — 24 entries pinned to `METRIC_SPECS` labels via forcing-function test.
- [x] **Per-branch trend overlay** (line-chart era — superseded by Session 41 bar charts).
- [x] **Attempts distribution** row in the Outcome block (`1: 91% · 2: 7% · 3+: 2%`).
- [x] **Latency share-of-total** per stage, with single section caption labelling the tri-tuple `p50 | p95 | share` once at the top.
- [x] **KB Source Coverage** panel under Failures — never-retrieved / retrieved / off-canon, sorted ascending. New `src/kb_corpus.py`.
- [x] **Deployment markers** on Trends investigate mode (line-chart era — removed in Session 41 with investigate mode).
- [x] **PRD published** as Issue [#39](https://github.com/AlejandroFuentePinero/digital-twin/issues/39) — canary set + drift detector. `needs-triage`.

**Session 41 (Trends rewrite + UX polish + audit):**
- [x] **Bar-chart redesign** — line/time-series charts replaced with grouped bars. 4 windows × 5 branches per chart. Investigate mode + deployment markers + prior overlay all removed.
- [x] **Shared per-branch legend** at the top of the Trends tab (one strip serves every chart).
- [x] **Threshold caption + reference lines removed** from Trends entirely (Metrics tab owns "is this healthy?").
- [x] **Whole-card-clickable flag buttons** — `gr.Markdown` card + ghost link replaced with single `gr.Button` styled as a card.
- [x] **Neon-red flag styling** (`--flag-neon: #ff1f4e`); locally scoped, doesn't change global `--alert`.
- [x] **Heading hierarchy** — `.section-header-major` for top-of-tab landmarks, `.section-header` demoted for sub-sections.
- [x] **Time-period column headers** bigger + less faded.
- [x] **Severity-tinted backgrounds** on every metric row (warning amber, healthy green, orientation gray) — same density as alert rows; only ribbon colour + bg hue differ.
- [x] **Honest over-engineering audit** — operator-triggered evaluation. Outcome: stop dashboard polish, build canary, run Phase 5, iterate from real failures. See DECISIONS.md Session 41.

### Phase 4.5 canary (Session 42 — `#39` shipped)

50-question canary corpus + 5-drift-kind detector + Sentinel Canary tab. Closes the specific-question-regression blind spot identified in the Session 41 audit.

- [x] **Schema bump v2 → v3** on `InteractionRecord`: `is_canary`, `replicate_index`, `run_id` (all default to live-record shape so legacy v1/v2 records still parse).
- [x] **`DashboardModel` filtering** — `include_canary` / `only_canary` flags filter at construction. Default-off so live tabs never see canary records. New canary-only methods: `branch_match_rate(corpus)` + `tool_uptake_on_warranted(corpus)` (clean denominator fix for `LIMITATIONS::P8`).
- [x] **`src/canary_corpus.py`** — `CanaryQuestion` + `load_canaries()` with branch-validation as a forcing function.
- [x] **`data/canaries/corpus.json`** — 50 curated questions audited line-by-line against profile.md + KB + READMEs. Mixes pass-aimed / gap-aimed / calibration-aimed / refusal-aimed probes across all 5 branches.
- [x] **`src/canary_baseline.py`** — pointer storage at `data/canaries/baseline.json` (`freeze_baseline` / `read_baseline` / `resolve_baseline_records`). Cold-start safe (missing/stale pointer degrades to `None` / `[]`).
- [x] **`src/canary_drift.py`** — pure detector. 5 drift kinds × 2 severity tiers (branch_changed major, event_type_changed major, retry_depth_changed minor/major at 1↔3+, chunk_set_changed minor [Jaccard 0.4-0.7), major <0.4, latency_p95_regression minor >25%, major >50%). Stratified summary by branch + category.
- [x] **`src/canary_runner.py`** — CLI orchestrator + `_CanaryLogWriter` injecting `is_canary` / `run_id` / `replicate_index`. Pipeline-factory injection seam for tests. Flags: `--replicates`, `--corpus`, `--freeze-baseline`.
- [x] **Sentinel Canary tab** between Trends and Failures: drift summary banner (benchmark + latest-run dates with sha attribution), drift flag cards (severity-styled), per-question drift table (drifting-only with toggle), Re-baseline button.
- [x] **Auto-refresh deliberately not wired.** `ensure_fresh_canaries` exists as a helper but `build_app` does not call it on launch. Operator triggers the batch via CLI on their cadence (50q × 3 replicates ≈ 30 min, ~$1.50/run). Memory pinned: `feedback_canary_manual_run.md`.

**Deferred from Phase 4.5 canary, re-open if Phase 5 surfaces demand:**

- Inline sparkline tables for the 3 health blocks on the Canary tab. `render_sparkline` helper exists; the matplotlib-PNG-base64-in-table renderer is the missing piece. Low priority until the operator has seen real drift signals and decides whether sparklines are load-bearing.
- LLM-as-judge `answer_drifted` flag kind — defer until keyword matching against `expected_keywords` proves too brittle in practice.
- Cost tracking on canary runs (`tokens_in`, `tokens_out`, USD) — parallel concern, separate ticket.

**Canary follow-ups identified in Session 62 (post drift-detector cleanup):**

- **Corpus cleanup** — drop fuzzy off-topic questions ("What did you have for breakfast?", "What's your favourite colour?") that have no defensible correct branch and will keep firing `branch_changed` on every run. Corpus-design issue, not detector issue.
- **`branch_changed` unanimous-vote tightening** — current detector fires on majority shift across N=3 replicates; a single flipped record can swing 2/3-vs-2/3 majorities. Tighten to require unanimous vote (3/3 vs 3/3) before flagging. Reduces false-positive rate on borderline questions without losing real signal.
- **Per-question stability scoring** — some questions have high inherent variance (we discover which by running them); the detector treats them all equally. Could compute per-question stability from accumulated trajectory runs and downweight chronically-unstable questions.

### Explicitly punted as YAGNI (reopen if signal demands)

Cohort cross-tabs (e.g. conversion-by-branch); CSV / JSONL export; pagination; custom date-range picker; multi-metric overlay in investigate mode; side-by-side attempt diff; configurable thresholds via UI; cost tracking (`tokens_in` / `tokens_out`); KB version stamp in records; materialised daily aggregates. **Phase 4.5-deferred:** Metrics-tab branch-filter dropdown (per-branch trends in Trends covered the use case at zero new Metrics-tab chrome); p99 latency (p50 + p95 + share is enough); LLM-evaluated gap rate (separate evaluator dependency, doesn't add over `knew_answer`); retrieval entropy / Jaccard across question pairs (too noisy at portfolio scale; KB Coverage covers most of the same signal more cheaply).

---

## Phase 5 — Break the live system  ✅ closed (Session 56, 2026-05-07)

**(a) Adversarial probe — data-gated additions (default zero):**
- [x] Local probe session, 50-question curated regression suite executed (`docs/HUMAN_EVAL_QUESTIONS.md::Phase 5 close-out`). 54 records logged, 0/54 exceeded 60s wall-clock.
- [x] Identify actual failure modes from log review. Two persisting patterns: `LIMITATIONS::P8` (0/7 tool fire on initial named-entity drills) + new `LIMITATIONS::O8` (guardrail mis-flags real content as fabrication on cross-branch conversation history).
- [x] **Default expectation honoured: zero new content added.** The 7 stories in `personal_stories`, 5 entries in `gap_inventory`, and the deflection rule held up across every dimension the regression probed.
- [x] Two structural fixes shipped instead: Session 56 hang fix (retry-policy filter + exception handling + timeouts) and tool architecture rewire (open `fetch_project_readme` to TECHNICAL/GAP/GENERIC + rewrite `TOOL_RULES`).
- [x] v5 eval skipped — no eval-relevant KB content changed. v4 (MRR 0.866 / accuracy 4.56) stays the baseline.
- [x] Issue `#4` closed; `needs-triage` stripped.

**(b) Canary baseline read — superseded by post-#45 contract:** the original three signals (branch-misroute / tool-uptake-on-warranted / bridging-instead-of-gap) were defined on a mechanism contract — `expected_branch` / `requires_tool` / `expected_event_type` — that PRD `#41` slice 4 retired in favour of an outcome contract (`outcome_accuracy` / `keyword_coverage` / `red_flag_rate`). Session 55's re-freeze (`run-20260505-132248-4aeb15`) ran the new contract and triaged the result there: 39 / 42 misses are the architectural seam logged as `LIMITATIONS::P17` (deferred until Phase 5 traffic shows the cost); 3 / 42 are acceptable model variance. **No live actions remain on thread (b).** Re-validation against the new baseline (Session 56, this entry) confirmed no genuine generator-side residue: walk-through-shape TECHNICAL records that skipped `fetch_project_readme` produced recruiter-quality answers from KB chunks alone — the system's "I have what I need" judgment is correct, and the post-#45 outcome contract scores those records correctly via `outcome_accuracy`.

The canary baseline is now a Tier B trajectory anchor (deltas from `run-20260505-132248-4aeb15`), not a Phase 5 work surface. The adversarial probe (thread a) is the discovery surface for new failures.

---

## Phase 6 — HF Dataset migration

Sliced into five GitHub issues (`#46`–`#50`). Slices A / B / C / D / E closed Sessions 57 / 58 / 59 / 60 / 61.

- [x] **Slice A — Buffered HF writer + reader round-trip (`#46`).** `LogBuffer` (in-memory + disk-backed at `data/logs/.hf_buffer.jsonl`). `HFLogWriter` (non-blocking append, size-or-time flush, group-by-UTC-date commits, append-don't-overwrite, background poller). `HFLogReader` (per-day file download + dedup on `(session_id, turn_index, run_id, replicate_index)` — slice's single dedup choke point). `make_log_writer()` factory keyed on `DIGITAL_TWIN_LOG_BACKEND=local|hf`; hf path auto-starts thread + registers `atexit` stop. `Alejandrofupi/digital-twin-logs` private dataset created. Opt-in `HF_INTEGRATION_TEST=1` round-trip verified.
- [x] **Slice B — Graceful shutdown + crash recovery (`#47`).** `HFLogWriter.__init__` triggers an immediate flush when `data/logs/.hf_buffer.jsonl` was non-empty at construction (records left behind by a crashed process ship within seconds of restart, not at the next size/time trigger). New `install_sigterm_handler(writer)` free function in `hf_log_writer.py` registers a SIGTERM handler that calls `writer.stop()` then `sys.exit(0)`; wired into `app.py` next to `make_log_writer()`. Local backend is a no-op (no `stop` method). End-to-end manual verification against the real HF Dataset passed for both halves (crash recovery + SIGTERM). +5 unit tests; suite at 572 passing.
- [x] **Slice C — Read-time schema migration (`#48`).** New `src/schema_migrations.py` declares `REQUIRED_FIELDS` (the 11 fields required at every schema version) + `OPTIONAL_DEFAULTS_BY_VERSION` (cumulative optional sets for v1 / v2 / v3 / v4) + `SchemaVersionHandler(record, target_version=SCHEMA_VERSION)` + `MissingRequiredFieldError(ValueError)`. Future-version records pass through unchanged with one warning so a producer running ahead of the reader can't crash the dashboard. Handler runs upstream of `InteractionRecord.model_validate` in `_parse_jsonl_to_records`; `LocalReader.read()` now shares that helper with `HFLogReader.read()` (one-line refactor) so the wiring covers both. On-disk records are never rewritten — backfilling defeats the read-time-migration purpose. +10 unit tests (8 handler + 2 reader-integration); suite at 582 passing.
- [x] **Slice D — Sentinel HF auto-detection + log writer health panel (`#49`).** `log_reader.make_log_reader()` factory keyed on `HF_TOKEN` + `HF_DATASET_REPO` (mirrors `make_log_writer`); `HF_TOKEN` set + `HF_DATASET_REPO` missing raises rather than silently degrading to local. `--local` CLI flag (`sentinel.py` `_parse_cli_args`) forces `LocalReader` even when both env vars are set — operator escape hatch for inspecting dev logs in a shell that has prod creds exported. `HFLogReader` now caches the repo listing + per-file downloads for the session lifetime; subsequent `read()` calls re-walk the in-memory cache, opening multiple Sentinel panels off the same reader doesn't burn an HF API call per panel. `huggingface_hub`'s default `~/.cache/huggingface/` is the on-disk layer. `invalidate_cache()` is the Refresh-button hook. `HFLogWriter.flush` now uploads `hf_writer_state.json` on every attempt (success OR failure) with `last_flush_time` / `buffer_size` / `last_error`; the state upload is wrapped in its own broad `except` so a state-upload failure can't mask a successful data flush or break the next retry. New Sentinel "Log writer health" panel under Metrics reads the state file via `hf_log_writer.read_writer_state` and renders the three rows; local backend + cold dataset + transient fetch errors all degrade to a placeholder rather than crashing. +16 unit tests (7 reader-factory/cache + 5 writer state-file + 4 panel); suite at 598 passing.
- [x] **Slice E — contacts.jsonl through the same HF abstraction (`#50`).** New `src/hf_contact_log.py` with `HFContactWriter` (subclasses `HFLogWriter` via class-attr overrides `PATH_PREFIX="contacts/"` + `WRITES_STATE_FILE=False` — inherits all flush / thread / crash-recovery / SIGTERM-drain machinery) and `HFContactReader` (fresh class — different per-day file regex `^contacts/...`, dedup on `(session_id, timestamp)`, per-session caching mirroring `HFLogReader`). `make_contact_writer` / `make_contact_reader` factories in `contact_log.py` mirror the interaction-log pair: writer keyed on `DIGITAL_TWIN_LOG_BACKEND`, reader keyed on `HF_TOKEN` + `HF_DATASET_REPO`. `install_sigterm_handler` now variadic so one signal drains both the interaction-log writer and the contact-log writer; one writer's stop failure doesn't block the other. `read_provided_session_ids()` falls through to `make_contact_reader()` when called with no args, so Sentinel becomes HF-aware automatically (no Sentinel-side changes needed for slice E). Buffer at `data/logs/.hf_contact_buffer.jsonl` (separate from interaction-log buffer). Slice-D's `hf_writer_state.json` deliberately not emitted for contacts — too low-volume for staleness signal to be meaningful. +21 unit tests (4 writer + 5 reader + 7 factories + 3 sigterm-multi + 2 read_provided_session_ids back-compat); suite at 619 passing.

---

## Phase 7 — Deploy to HuggingFace Spaces

Sliced into two GitHub issues (`#51`, `#52`).

- [x] **Slice 1 — Space deploy + production polish + smoke-test pass (`#51`).** README YAML frontmatter; `requirements.txt` mirroring `pyproject.toml`; `app.py` polish (`WELCOME_TAGLINE` + `PRIVACY_NOTE` constants, privacy footer); `.privacy-note` CSS; 4-test `tests/test_app_session_state.py`; `scripts/deploy_to_space.py` (Hub API — `git push` rejected by Spaces' >10 MB pre-receive hook); `docs/deployment-runbook.md`. Live at <https://alejandrofupi-digital-twin.hf.space>; smoke test passed 4/5 branches (LOGISTICAL not asked), p50 ≈ 12.7 s / p95 ≈ 17.3 s on cpu-basic; first production write to `contacts/` succeeded and joined to its 6-turn session via `session_id`; slice-D writer-health state file fresh on prod. Cold-start latency capture deferred to first organic visitor on a slept Space. v6 eval skipped — no eval-relevant content changed since v4. Suite +4 (619 → 623).
- [ ] **Slice 2 — Portfolio iframe embed (`#52`).** Add the iframe + fallback link to the home page on `AlejandroFuentePinero/alejandrofuentepinero.github.io` (Jekyll/AcademicPages); run the parent-PRD step 12 (embedded smoke test) on desktop + mobile.

---

## Open implementation details (not blocking architecture)

- Final phrasing for: deflection rule, periodic-invitation closing line, contact-form copy.
- Selection of 5–8 flagship project READMEs to cache in `data/readmes/`.
- Formal test plan (one document covering all phases — written when test surface is concrete).
- **Gradio UI polish session** — dedicated standalone session (planned per Session 26 smoke-test feedback; not gated on Phase 3+ work). Concrete items surfaced from live testing:
  - Welcome message + framing (currently a one-line Markdown header)
  - Theme review (cohesion across chat / accordion / form / buttons)
  - Mobile responsiveness (untested; chat layout assumes desktop width)
  - Form layout polish — initial Session 26 fix (Accordion + tighter row layout) was a quick fix; revisit for visual hierarchy, spacing, microcopy
  - Accordion default-open vs default-closed when first triggered
  - Loading states / response streaming (currently full reply appears at once)
  - Visual feedback for tool fetches (TECHNICAL turns currently silent during the multi-second tool loop)
  - Error state UI (canned-refusal currently appears as a regular assistant message)
- **Replace [`data/readmes/digital_twin.md`](../data/readmes/digital_twin.md) with Alejandro-authored version.** Currently a Claude-authored placeholder distilled from `CLAUDE.md` + `docs/adr/` + a direct read of `src/`. Architecturally accurate but not in Alejandro's voice. The self-reference doc is the one TECHNICAL recruiters most likely to drill into ("how does this very chatbot work?"), so voice and emphasis matter. Keep the locked Q11 shape (Source link → What it is → Architecture → Key engineering decisions → Stack and discipline) when replacing. Two release-blocking gates in [`RELEASE_CHECKLIST.md::Portfolio / external`](./RELEASE_CHECKLIST.md): (1) content replacement, (2) Source link resolution (the `AlejandroFuentePinero/digital-twin` repo is currently private — the GitHub Source link returns 404 for unauthenticated visitors; either make the repo public or redirect the Source line to a public resource).

---

## Three ground rules (governance)

1. **The bar for putting content in the agent's mouth is "would Alejandro say this verbatim to a recruiter on a phone call?"** — content lands on observed failure, not speculation.
2. **Frame is loaded by branch; Substance is retrieved.** No duplicate sources of truth.
3. **Eval questions must be KB-grounded.** Adding eval before content measures absence.

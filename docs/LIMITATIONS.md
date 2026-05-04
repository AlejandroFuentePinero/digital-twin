# Digital Twin — Limitations and Operational Risks

A living register of system-wide limitations and operational risks. Entries are **observed** (empirical, with evidence from logs and smoke-tests) or **predicted** (architectural, from ADRs). Each entry has an explicit **trip-wire** — the condition under which it stops being a watch-item and becomes a triaged issue.

This doc complements `docs/DECISIONS.md` (per-session log) and `docs/adr/` (point-in-time architectural decisions). Entries that recur across sessions get promoted from session watch-items into here. Entries here graduate to **Resolved** with a forward-pointer to the fix when the trip-wire condition is met and addressed.

**Update cadence:** after every smoke-test round, ADR change, or production incident. **Owner:** whoever is closing the session in which the entry surfaced. **Review:** before any release per [`RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md).

> **Charter:** [issue #20](https://github.com/AlejandroFuentePinero/digital-twin/issues/20). Block reason ("blocked by #15 so misclassification rate can be described from observation rather than prediction") cleared in Session 21 — empirical baseline established by smoke-test rounds #21 (R1) and #26 (R2).

---

## Observed

### O1 — First-attempt fabrication rate on no-KB-coverage probes

**Status:** Observed (R1 baseline, R2 confirmed).

The generator sometimes fabricates plausible content rather than emitting the canonical gap phrase when the question hits a no-KB-coverage edge. R2 logged 3 first-attempt fabrications across 27 turns (~11%): Q2.5 invented "Model Control Plane" as the MCP acronym; Q8.1 invented a specific disagreement-with-collaborator scenario; Q8.3 follow-up invented a "2 to 4 weeks" notice period. R1 had a comparable rate. **In every case the guardrail caught the fabrication and the retry produced the correct user-visible answer**; the architectural defense (rules → grounding → guardrail → retry → canned-refusal floor) worked end-to-end.

**Evidence:** Session 19 (R1 analysis), Session 21 (R2 analysis). Log records `data/logs/interactions.jsonl` lines 7–32 (R1) and 33–59 (R2).

**Why this is logged but not fixed today:**

- The smoke-test sample is *deliberately* concentrated on the failure surface (adversarial pressure, no-KB-coverage probes, ambiguous prompts). 11% on a stress-test sample is not the real-world recruiter-traffic rate.
- The intervention space is narrow. The gap-phrase rule already says "prefer refusal over fabrication." Adding a duplicate or vaguer rule wouldn't change first-pass behaviour. Per `feedback_accept_uncertainty_over_constraint`, hard new constraints on probabilistic behaviour have a cost-benefit that doesn't currently favour shipping.
- The architectural response to fabrication risk **is** the retry loop. It works.

**Trip-wires (any one triggers a triaged issue):**

1. ≥6 / ~27 first-attempt fabrications in a future round of similar shape (roughly double today).
2. Monotonic rise in first-attempt rejection rate across three consecutive rounds.
3. A fabrication that escapes the guardrail and ships to the user.
4. A pattern emerges where the *same* probe shape fabricates repeatedly (e.g. MCP acronym — see O3).

**What Sentinel needs to make this trackable cleanly:** `attempts[*].rejection_reason` field on the interaction log record, with a small enum (`fabrication`, `bridging`, `scope`, `tone`, `multi-turn-coherence`, `other`). Today's `interaction_log.py` carries `attempts[*].guardrail_feedback` (free-text) but no structured reason — so cross-session aggregation requires text classification of the feedback strings. Add the field when Sentinel work begins.

**Canary baseline (Session 42, 2026-05-04, run `run-20260504-121937-9af6fb`):** the 8 gap-aimed canary questions (C006-C009 niche-tech + C019-C022 out-of-scope) produced **3 gap-phrase emissions and 5 answered-instead-of-gapped** events. That's a 62.5% bridging rate on a curated probe set — same shape, different sample frame from the smoke-test trip-wire. Doesn't directly trip the existing trip-wires (which were defined on adversarial-probe sample shapes), but is the cleanest signal yet that the bridging behaviour is the dominant first-attempt response to no-coverage probes. **Phase 5 will read the 5 specific records to decide whether to tighten `rules.GAP_PHRASE` enforcement, add the question shapes to a curated negative-example list, or treat the bridging behaviour as acceptable on certain niche-tech probes** (some bridging may be honest — "I haven't used kdb+/q but I have used time-series databases X, Y" — and the right answer depends per-record).

---

### O2 — TECHNICAL classifier over-firing on tool-name probes

**Status:** Observed (R1, R2 — same shape both rounds).

`gpt-4.1-nano` over-predicts the `TECHNICAL` label on tool-shape probes that are actually GAP-shape ("Have you used X?", "Have you written Y?"). In R2, five turns mis-predicted: Q1.4 (CUDA), Q2.5 (MCP), Q4.1 (Bayesian), Q4.2 (deep neural networks), Q5.1 (Python function), Q7.2 (Bayesian → AI bridge), Q8.2 (Digital Twin classify). R1 produced the same pattern. Filter-fallback to `GENERIC` saves these today because `TECHNICAL` is not yet in `branches.REGISTRY`.

**Evidence:** Sessions 19, 21. `classifier_labels` ≠ `branch` on these turns in both rounds.

**Why this is logged but not fixed today:**

- The pipeline filter (slice 6 of #15) catches every misroute and falls back to `GENERIC`. User-visible behaviour is correct.
- Fixing the classifier prompt to disambiguate tool-shape probes is over-engineering today; the filter handles it.

**Trip-wire:** **when [issue #18](https://github.com/AlejandroFuentePinero/digital-twin/issues/18) (TECHNICAL branch) lands, the filter no longer fires for these turns and they will route to a TECHNICAL prompt that does not include `active_learning`.** This is a known compounding risk specific to #18.

**Action when #18 is picked up:** add a smoke-test sub-suite that asks GAP-shape tool probes (Bedrock, Aurora Serverless, Terraform, etc.) under a registry that includes TECHNICAL. Verify either (a) Layer 3 (KB chunk for active-learning) is sufficient grounding when Layer 1 (`active_learning` profile section) is not loaded, or (b) extend `active_learning` to TECHNICAL's `profile_sections` so the deterministic in-progress framing carries over.

---

### O3 — MCP-acronym confab pattern

**Status:** Observed twice (R1, R2 — different invented expansion, identical failure shape).

Q2.5 ("Have you used MCP in production?") triggered a first-attempt acronym fabrication in both rounds. R1 invented "Multi-Cloud Platform"; R2 invented "Model Control Plane." The `active_learning` chunk (loaded via retrieval — verified in `retrieved_chunks` for both turns) explicitly says "MCP at production scale" and the active_learning profile section explicitly says "Model Context Protocol." The model had the data in its context window in both cases and didn't read it on first pass. Guardrail caught both; retries corrected both to "Model Context Protocol."

**Evidence:** Log record line 15 (R1, attempt 1: "MCP (Multi-Cloud Platform)"); log record line 41 (R2, attempt 1: "MCP (Model Control Plane)").

**Why this is logged but not fixed today:**

- Two occurrences = pattern noted, not yet pattern confirmed.
- The data *is* in the prompt; this is a generator-attention issue, not a content gap. Not solvable today by prompt rules alone.

**Trip-wire:** third occurrence with the same shape (acronym fabrication on MCP or on any other multi-character active-learning keyword). At three, investigate retrieval ranking + chunk position + active-learning chunk visibility on first-pass attention. Possible interventions: surface the keyword expansion earlier in the chunk; add a brief glossary chunk for high-confab acronyms; tighten the active-learning section's framing.

---

### O4 — Multi-turn drill-down offer-then-can't-deliver

**Status:** Observed (R2, novel — exposed by a user follow-up turn that did not exist in R1).

The soft conciseness rule (`concise_disclosure`, shipped #25) introduces a drill-down offer pattern at the close of most answers ("happy to go deeper on X if useful"). In R2 the user followed up on Q8.3 turn 1's offer with *"yes please, provide specifics"* — the model fabricated a "2 to 4 weeks" notice period (caught by guardrail), retried with the gap phrase but contradicted the prior offer (caught by guardrail for multi-turn coherence breach), and on attempt 3 acknowledged the offer-retract mismatch and redirected. **Used 3 of 3 retries on a single turn** — the entire safety budget consumed.

**Evidence:** Log record line 59 (R2 Q8.3 follow-up, three attempts).

**Why this is logged but not fixed today:**

- Net user-visible outcome was correct (attempt 3 shipped a coherent answer).
- One occurrence; pattern not yet confirmed.
- The soft framing of the rule is a deliberate choice (Session 20) and shouldn't be tightened on a single failure.

**Trip-wire:** second occurrence of the offer-then-can't-deliver shape on a multi-turn drill-down, OR a turn that exhausts the retry budget and ships canned-refusal because of this pattern.

**Action when the trip-wire fires:** soften the offer wording in `CONCISE_DISCLOSURE` toward "happy to share what's documented on X if useful" rather than open-ended "more on X". Bias the offer language toward what the model can verifiably deliver.

---

### O5 — Classifier confidence variance on edge cases

**Status:** Observed across 3 rounds (R1, R2, Session 26 live smoke-test) — variance now confirmed to swing the **branch label itself**, not just the confidence number.

`gpt-4.1-nano` returns substantially different routing decisions on the same probe across rounds:
- **R1 / R2 ambiguous probes (confidence variance only):** Q5.2 confidence 0.8 → 0.4; Q5.3 confidence 0.9 → 0.2. Both routed correctly via filter-fallback or low-confidence override.
- **Session 26 (label variance):** *"How does the Digital Twin classify questions?"* routed to **TECHNICAL@0.9** in Session 24 verification but to **GENERIC** in Session 26's live test. Different branch entirely; the tool wasn't available because GENERIC has no tools. Trip-wire #1 from the original entry now fired (a confidence drop that flips routing in a way that misroutes the answer).

**Mitigations layered post-Session 26:**

1. **Classifier prompt sharpened (Session 26 / commit `<TBD>`):** TECHNICAL definition now explicitly covers meta-questions about the Digital Twin chatbot itself ("how does it classify questions?", "what model are you?"), with the canonical mis-routed probe added as a positive example. Friction-lock test (`tests/test_classifier.py::test_system_prompt_includes_digital_twin_self_reference_in_technical_definition`) pins this against regression. **This is the small obvious fix per the discipline of "don't engineer over variance."** Real fix is Sentinel-driven aggregation over time, not reactive engineering.
2. **Low-confidence override to GENERIC** (`CLASSIFIER_CONFIDENCE_THRESHOLD = 0.5`, Session 18) still in place; handles the confidence-variance-only case.

**Trip-wires (any one warrants further intervention):**

1. ~~A confidence drop that flips routing in a way that misroutes the answer~~ — **fired Session 26; classifier prompt sharpened as small fix.**
2. The Session 26 fix doesn't hold — same probe shape mis-routes again post-prompt-update in R3 or live observation.
3. A new probe shape mis-routes in a different direction (e.g., GAP-shape probe routing to TECHNICAL persistently).

**Action when 2 or 3 fires:** consider broader classifier-prompt restructuring OR a deterministic override layer in pipeline (last-resort — would reintroduce keyword brittleness routing was supposed to avoid). Tracking is via Sentinel's per-branch routing aggregation (`branch_distribution` in the Health Overview, plus the Failure Feed branch filter).

---

## Predicted (architectural, not yet observed in production)

### P1 — Mid-conversation prompt switching

**Status:** Predicted (ADR-0003 §Operational risks). **Currently empirically clean** across R1+R2 — Session 6's GENERIC→GAP→GAP flip across three turns produced coherent verb calibration on every turn.

A session re-classifies turn-by-turn. The model sees a different system prompt on different turns; earlier-turn instructions are gone from the working set even though earlier-turn responses remain in the message history. Style or calibration shifts across rule-set changes are possible.

**Mitigated by:** `identity` profile section + the four universal rules (`persona`, `scope`, `security`, `numerical_completeness`) loading on every branch — holds cross-turn consistency on the dimensions that matter most. Not mitigated for branch-specific rule continuity.

**Trip-wire:** a flip that produces incoherent tone (e.g. expertise-rung verbs on one turn flipping to trained-rung verbs on the next over the same skill) or verb-leak from a previous turn's calibration into the current turn's branch.

---

### P2 — Hidden state across `rules.py`, `profile.md`, and `branches.py`

**Status:** Predicted (ADR-0003 §Operational risks).

A `BranchSpec` references rule keys and section names as strings; the composer dereferences them at runtime. Reading `branches.py` alone does not reveal what a branch *actually composes* — that requires `rules.RULES` + `profile.section(...)` + the composer's two-loop logic. Cognitive overhead vs. a single prompt template.

A second-order risk: the same composed prompt loads to **both** generator and guardrail (per ADR-0003 drift prevention), so a rule change that fixes generator behaviour can silently change guardrail behaviour. #25's soft conciseness rule was the first concrete test of this — it loads to both surfaces, R2 showed no guardrail over-rejection on length grounds, so the soft framing held.

**Mitigated by:** smoke-test discipline (R1 + R2 caught nothing here), unit tests on dereferencing.

**Trip-wire:** a prompt change lands the targeted generator effect but inadvertently changes guardrail strictness in the wrong direction. Smoke-tests are the catch.

---

### P3 — Universal rules cannot be branch-tuned

**Status:** Predicted (ADR-0003 §Operational risks).

`UNIVERSAL = ["persona", "scope", "security", "numerical_completeness"]` loads identically on every branch. If a future branch needs a different scope or security framing (e.g. LOGISTICAL questions arguably have a *narrower* scope than GENERIC), today's architecture has no override mechanism — only "make the rule generic enough to cover all branches."

**Trip-wire:** a branch's needs genuinely conflict with a universal rule. Most likely surface: when `LOGISTICAL` (#19) lands, the `scope` rule may be over-broad for logistics-only probes. Verify behaviour and revisit if needed.

---

### P4 — KB is static; no live fetch

**Status:** Predicted (architectural choice).

The knowledge base is ingested at build time. Profile content, project metrics, and KB facts cannot be updated mid-session. New facts (a new publication, a project milestone, a role change) require re-ingest. The TECHNICAL branch's `fetch_project_readme` tool (#18 / Session 24) is the *only* model-callable mechanism for fresh content — and it reads from local distilled files, not the live web.

**Decision provenance:** [`DECISIONS.md::Session 1 (2026-04-24) → § 3 Web fetch: links-as-pointers, no live fetch in v1`](./DECISIONS.md#session-1-2026-04-24--knowledge-base-and-evaluation-set). Rationale: *"For a personal digital twin answering known facts about a known person, live web fetch adds latency and failure modes for no benefit. The knowledge base is the authoritative source."*

**Trip-wire:** a recruiter asks about something that demonstrably changed since last ingest, and the system answers from stale data. Mitigated today by date-stable KB framing (#24's "May 2026 – present" rather than "starts 13 May 2026").

---

### P5 — Single-user, no cross-session memory

**Status:** Predicted (architectural choice).

Each Gradio session gets a fresh `session_id` and `turn_count`. There is no per-recruiter persistence: a returning visitor is indistinguishable from a first-time visitor. The `contact_provided` flag (planned for #16) will be per-session, not per-recruiter-identity.

**Trip-wire:** the system would clearly improve with cross-session memory (e.g. a recurring recruiter where the system could pick up where it left off). Out of scope for the current design.

---

### P6 — Eval-vs-user-behaviour caveats

**Status:** Predicted (long-standing).

The v3 eval (`eval/tests.jsonl`, 149 Q&A) and the v4 eval (#2, planned) measure retrieval and answer quality on synthetic recruiter shapes. **They do not measure the routing surface, fabrication rate, or multi-turn coherence** that are the failure modes most visible in live smoke-tests (#21, #26). Treating eval scores as the sole quality signal would miss the failure modes that matter most under real usage.

**Trip-wire:** an eval score change that does not match a smoke-test signal change. Use both.

---

### P7 — Deflection rule scoped to BEHAVIOURAL only

**Status:** Predicted (architectural choice, Session 23 / #17).

The `deflection` rule is registered in `branches.REGISTRY` only for `BEHAVIOURAL`. Its body governs (a) story selection from the `personal_stories` section via the routing guide, and (b) honest non-fabrication ("decline + offer Alejandro contact directly") when no story maps. The "decline + offer contact" half is a generally useful pattern; it is *not* currently exposed to `GENERIC`, `GAP`, or `LOGISTICAL`.

**Why this is the right scope today:**

- BEHAVIOURAL is the most open-ended branch — its inputs ("tell me about a time you…") cannot be reliably constrained by KB grounding, so the explicit no-fabrication-with-contact-offer guidance is highest-value there.
- The other branches each have their own anti-fabrication mechanism: generator framing (universal) says "Do not invent facts" and emits the gap phrase; `calibration_ladder` (GAP) governs evidence-calibrated verbs and the gap-phrase fallback; LOGISTICAL's section content already encodes "happy to discuss directly" redirects per item.
- KB-grounded branches (GENERIC, GAP, LOGISTICAL, future TECHNICAL) lean on retrieval as the primary fabrication defense — the principle is "answer from grounded context or emit the gap phrase," enforced by both generator framing and guardrail. Open-ended branches need stronger deflection precisely because grounding is thinner.

**Trip-wires (any one promotes this to Observed and triggers extracting a cross-branch `offer_contact` rule):**

1. A future smoke-test shows `GENERIC`, `GAP`, or `LOGISTICAL` fabricating in a shape where a "decline + offer Alejandro contact" pattern would have been more useful than the current bare gap phrase.
2. A pattern emerges where the gap-phrase response feels like a dead-end to the visitor (e.g. follow-up turns that re-ask the same thing, suggesting the visitor wanted a path forward, not just an honest "no").
3. TECHNICAL (#18) lands and, despite its `fetch_project_readme` tool, surfaces a fabrication shape (e.g. invented architecture details for a project not yet in the README registry) that an `offer_contact` rule would have caught more cleanly than retry-then-canned-refusal.

**Action when a trip-wire fires:** extract the "decline + offer Alejandro contact" half of `DEFLECTION` into a separate `offer_contact` rule (~3 lines: "If the answer would require fabricating to be useful, decline and offer Alejandro's direct contact at [email]"). Keep `deflection` for personal-stories-specific machinery (routing guide, STAR shape, no-extrapolation-from-KB-experience). Wire `offer_contact` into the `branch_rules` of whichever branch the trip-wire fired on.

**Why split rather than just add `deflection` everywhere?** Today's `deflection` body is deeply coupled to personal_stories machinery (routing guide, "never extrapolate from KB experience entries"). Loading it into GENERIC or LOGISTICAL would be incoherent — those branches have no routing guide and don't draw from `personal_stories`. The right factoring on a trip-wire firing is to pull out the orthogonal "offer contact" half rather than promote the whole rule.

**Related:** O1 (first-attempt fabrication rate) — if O1's trip-wire fires *and* the new fabrications are on non-BEHAVIOURAL branches, P7 is the structural follow-up.

---

### P9 — Contact-form keyword detector is heuristic

**Status:** Predicted (architectural choice, Session 26 / #16 expansion).

The explicit-request trigger uses a regex pattern list (`session_state.EXPLICIT_REQUEST_PATTERNS`) to detect phrases like *"how can I contact him?"*, *"reach out to Alejandro"*, *"schedule a call"*. Conservative-by-design — high precision (low false-positive risk) but accepting false negatives. Patterns target the recruiter intent of "I want to reach Alejandro directly," not the appearance of words like "email" or "contact" in unrelated questions ("what email service does he use?").

**Why this is logged but not fixed today:**

- LLM-based intent classification would be more accurate but adds a per-turn model call cost + latency for a UX nicety.
- Turn-3 invitation + gap-event trigger both cover the "form should appear" case the detector misses — false negatives degrade UX gracefully (user sees form by turn 3 anyway).
- False positives are worse (form pops up out of nowhere); pattern conservatism prioritises precision over recall.

**Trip-wires (any one promotes to Observed):**

1. Smoke-test or live observation surfaces a recruiter-shape phrase the detector misses repeatedly (e.g., "I'd like to discuss the role" — clearly contact intent but no detector match).
2. False positive observed in the wild — form appears unexpectedly because a phrase matched a pattern incorrectly.
3. Pattern list grows past ~20 entries — at that point the heuristic complexity is approaching what an LLM classifier would handle more cleanly.

**Action when a trip-wire fires:**

- Single false negative shape recurring → add a tightened pattern targeting that specific phrase shape.
- False positive → tighten the conflicting pattern; add a unit test pinning the negative case.
- Pattern list bloating → migrate to LLM-based classification (`gpt-4.1-nano` for cost), accept the ~200ms latency hit. Could reuse the classifier module's pattern (one-shot LLM call returning `bool`).

**Companion observability:** Sentinel could surface "turns where the user message contained 'contact' / 'reach' / 'in touch' words BUT explicit_request_seen wasn't latched" — a queryable signal for false-negative pattern discovery. Not yet built; would be a custom Failure Feed filter, not in the current Sentinel scope.

---

### P8 — TECHNICAL tool-uptake rate is unmeasured

**Status:** Predicted → **partially Observed** (Session 26 live smoke-test).

Session 26 surfaced inconsistent tool-uptake on TECHNICAL turns within a single session: turn 5 ("what is the top AI project in Alejandro curriculum") routed TECHNICAL ✅ but `tool_calls=[]` (model judged KB context sufficient and didn't fetch); turn 7 ("Job Intelligence Project recommendation pipeline") routed TECHNICAL AND fetched `job_intelligence_engine` ✅ AND grounded the answer cleanly. **Same session, same branch, different model decisions.** Classic stochasticity — exactly what this entry predicted.

**Discipline call (Session 26):** per the user's principle ("don't engineer over variance"), **no reactive intervention**. The right tracking mechanism is Sentinel-driven aggregation over a meaningful sample, not patching after every observed mis-fetch. Single-session evidence is too thin to justify changing tool_rules calibration or adding deterministic overrides. Watch-item documents the observation; further response gated on Sentinel signal.

**Original framing preserved below.**

The `fetch_project_readme` tool fires on the model's discretion — `tool_rules` describes *when to call* and *when not to*, but the model's actual decision is a black box. The interaction log captures every tool invocation that *does* happen (`tool_calls[{name, args, status, attempt_index}]`), but does not — and architecturally cannot — capture the model's reasoning for *not* calling when it arguably should have. Two concrete failure modes are possible:

1. **False negatives:** model routes to TECHNICAL on a project-deep question, judges the KB context sufficient, doesn't call the tool, and produces a shallower-than-warranted answer that the guardrail accepts. Log shows `branch=TECHNICAL, tool_calls=[]`; the answer reads OK in isolation but a tool fetch would have produced a materially better one.
2. **False positives:** model calls the tool on a question that didn't need it (e.g., a general "tell me about your projects"), bloating the prompt with a 1–2k-token README the model then half-uses. Log shows `tool_calls=[...]` but the tool result didn't move the answer.

**Why this is logged but not fixed today:**

- The wiring is unit-tested (`test_technical_classification_routes_to_technical_branch_with_transfer_principles`, `test_technical_branch_records_tool_calls_in_log_when_model_invokes_tool`) — *if* the model calls the tool, the system handles + logs correctly. The model's *decision* is what we can't unit-test.
- Per project policy (TESTING.md), no LLM API calls in pytest. Behavioural verification of "does the model call when appropriate" lives in the live smoke-test runbook, not unit tests.

**Trip-wires (any one promotes this to Observed):**

1. Live smoke-test (issue #18 task #24, or any future R3 round) surfaces a TECHNICAL turn where the model demonstrably should have called the tool and didn't, AND the answer is materially weaker for it.
2. Aggregate uptake rate over time (Sentinel's `technical_tool_uptake_rate` + Trend Explorer) shows TECHNICAL turns calling the tool at a rate that doesn't match the question shape (e.g., consistently 0% when realistic question mix should be 40-60%).
3. Inverse: model calls the tool on >70% of TECHNICAL turns including general "tell me about your projects" shapes — false-positive over-firing.

**Action when a trip-wire fires:**

- For false negatives: tighten `tool_rules`'s "When to call" clause with sharper triggers, OR add explicit affirmative cues like "if the visitor names a specific project, default to fetching unless the question is unambiguously general."
- For false positives: tighten "When not to call" with the offending pattern; add an explicit example of the false-positive shape.
- For aggregate misalignment without a clear shape signal: add an LLM-as-judge pass over `(question, branch, tool_calls, answer)` to label each turn as "appropriate / under-called / over-called" and surface the breakdown in Sentinel.

**What would help observe this cleanly:** a Sentinel panel showing `branch == TECHNICAL` turn count vs `len(tool_calls) > 0` count, broken down by question shape (project-named vs general). The aggregate `technical_tool_uptake_rate` exists today; the question-shape breakdown is not yet built (would be a custom Sentinel surface — `#34`'s `FlagDetector` ships `gap_rate_jump` / `new_cluster` / `repeat_failure` only, not question-shape disaggregation).

**Partial fix (Session 42, #39):** the Canary tab's `tool_uptake_on_warranted(corpus)` metric uses a clean denominator — only canary questions with `requires_tool=True`. Live `technical_tool_uptake_rate` keeps its noisy denominator (every TECHNICAL turn, regardless of whether the question warranted a tool call). The canary surface gives a sharp signal on a closed corpus; the live metric remains a coarse aggregate. Both are kept — they answer different questions.

**Canary baseline (Session 42, 2026-05-04, run `run-20260504-121937-9af6fb`):** **`tool_uptake_on_warranted(corpus) = 38.5%`** — 8 of ~13 `requires_tool=True` canary questions did NOT trigger a `fetch_project_readme` call. Tool call success rate when the tool *did* fire = 100% (so it's uptake, not reliability). This is the false-negative pattern (#1) materialising at corpus-relevant magnitude. Trip-wire #2 from the original entry ("Aggregate uptake rate over time shows TECHNICAL turns calling the tool at a rate that doesn't match the question shape") **fires** on the canary surface — the question shape is curated to be tool-warranting, and the rate is below 40%. Phase 5 should tighten `tool_rules`'s "When to call" with sharper triggers — the LLM advisor's earlier suggestion ("if visitor names a specific project, default to fetch unless unambiguously general") is the candidate language to test against the canary as a verification surface.

---

### O6 — Classifier routes specific-paper questions to GENERIC, losing TECHNICAL tool access

**Status:** Observed (v5 eval, Session 27 / #2).

Three v5 acc<4 failures share the shape: question explicitly names a publication (`What is the title of Alejandro's 2026 paper in Nature Climate Change?`, `What is the title of Alejandro's 2021 paper in Ecography?`, `How many supporting projects are in the LLM Engineering Lab, excluding the flagship?`) but the classifier returned low confidence (0.4–0.6) and the system fell back to GENERIC. GENERIC has no `fetch_project_readme` tool access, so the system can't pull the canonical readme to recover the title or specific count — it has to rely on whatever the KB chunks happen to surface, which often misses the verbatim title.

The semantic shape — "give me a fact about a specific named publication / project" — should arguably trigger TECHNICAL, but current classifier prompt phrasing leaves these in the borderline zone where the 0.5 confidence threshold floors them at GENERIC.

**Why this is logged but not patched here:**

- Issue #2's scope is measurement, not classifier tuning.
- A reactive classifier-prompt tweak (adding "what is the title of paper X" / "name a specific detail of project Y" as positive examples) was scoped in #27 and **deliberately rejected on 2026-05-04** — it is prescriptive overfitting to three eval cases, not a structural fix. Direct violation of `feedback_accept_uncertainty_over_constraint`.
- A defensive universal-rule promotion (promoting `deflection` and `calibration_ladder` to `UNIVERSAL`) was also scoped in #27 and **deliberately rejected on 2026-05-04** — it contradicts `P7`'s explicit architectural rationale (none of P7's trip-wires have fired), `DEFLECTION`'s body is coupled to `## personal_stories` machinery and is incoherent in branches that don't carry that section, and `CALIBRATION_LADDER`'s body targets skill-shape probes specifically.
- Lowering the 0.5 confidence threshold across the board is *not* the right fix — it would let genuinely-confused borderline cases route to wrong specific branches more often.
- Honest reframing: a paper title is a factual lookup about a publication, not a "deep technical question about projects, methods, or code" by the current TECHNICAL branch definition. The classifier is correctly uncertain; GENERIC + retrieval is the right home. The bottleneck (if any) is KB-side — whether `publications.md` chunks surface canonical titles verbatim and rank-surface for title-shape queries — not classifier-side.

**Trip-wires (any one promotes priority):**

1. A future custom detector flags `category="title fetch" AND branch="GENERIC" AND attempts > 1` as a recurring pattern in production logs over a meaningful sample. (`#34`'s shipped detectors — `gap_rate_jump` / `new_cluster` / `repeat_failure` — would catch the *repeat-failure* shape if the same paper-title question reappears 3+ times in 7 days, but not the broader `category=direct_fact` cohort signal; that needs a new detector.)
2. R3 or future smoke-test surfaces a recruiter probe asking for a paper title and getting a generic deflection — repeated shape, not a single instance.
3. A future eval round shows the failure shape *expanding* (e.g. 3 → 6 specific-publication failures, or sibling shapes emerging where the system fabricates rather than emits the gap phrase).

**Action when a trip-wire fires:**

- First investigate KB-side: are the canonical titles present verbatim in `publications.md` chunks, and do those chunks rank-surface for the failing question shapes? Rerank-test before any classifier change.
- Only if KB-side investigation is clean, revisit classifier scope — but as a structural redefinition of TECHNICAL's boundary (does it cover factual-lookup-about-named-publication?), not as example stuffing.
- If misroute defense is still wanted at that point, the right factoring per `P7` is splitting `DEFLECTION` into a portable `offer_contact` half rather than promoting the whole rule.

**Companion observability:** Sentinel can surface this as `category=direct_fact AND branch=GENERIC AND classification_confidence < 0.5 AND question_mentions_paper_or_project()` — a boolean signal for misroute-to-fallback patterns. `#34`'s shipped `FlagDetector` doesn't model this shape today (its three detectors are `gap_rate_jump` / `new_cluster` / `repeat_failure`); the `confident_failure_rate` metric (#35) is the closest existing surface and the right place to start.

**Canary baseline (Session 42, 2026-05-04, run `run-20260504-121937-9af6fb`):** broader than the original specific-paper observation — `branch_match_rate(corpus) = 78.7%` (11 / 50 canary questions misrouted), with **mean classification confidence 0.873 across the corpus**. The misroutes aren't low-confidence-correctly-floored cases; they're confident-and-wrong. Phase 5 will read the 11 specific records to identify whether the misroute clusters by question shape (paper-title-shaped misroutes only? all-direct-fact misroutes? branch-specific?) and decide between (a) classifier-prompt sharpening on the dominant shape, (b) registering more positive examples, or (c) accepting the misroute when the answer surfaces correctly anyway via GENERIC + retrieval.

---

### O7 — TECHNICAL number-misread despite correct readme content

**Status:** Observed (v5 eval, Session 27 / #2).

Two TECHNICAL-routed v5 failures (high classifier confidence 0.9, model has tool access) still answer with the wrong specific number despite the readme carrying the correct figure:

- **JIE postings**: model answered `3,892` (the AI-JIE published Data Scientist subset figure, found in `ai_jie.md`) when the question was about JIE's training corpus (`6,100+`, now explicit in `job_intelligence_engine.md`'s Scale section). Either the model fetched the wrong key, fetched both and trusted AI-JIE's number, or found the AI-JIE figure in retrieval and ignored the JIE readme.
- **Price Predictor model count**: readme now lists 12 model families enumerated explicitly (4 baselines as separate rows: Constant, Linear, Random Forest, XGBoost; then MLP, ResNet, GPT-4.1-nano zero-shot, GPT-4.1-nano fine-tuned, Llama-3.2-3B base, Llama-3.2-3B QLoRA, GPT-5.1+RAG, Ensemble). Model still answered `8` by collapsing zero-shot+fine-tuned and base+QLoRA pairs into single entries.

These are not "readme content" failures — the content is correct and accessible. They're **model-reading failures**: tool-returned content is read sloppily under the same scope-creep instinct the citation rule addressed for paper metadata, but applied here to project numbers.

**Why this is logged but not patched here:**

- Issue #2's scope is measurement.
- The fix is a `tool_rules` tightening (e.g., *"When the visitor asks for a specific number from the project — count, score, dataset size — quote the readme verbatim and do not consolidate enumerated entries"*).
- A defensive measure could also be at guardrail level: numerical-completeness rule extended to flag answers that contain numbers absent from retrieved/tool context.

**Trip-wires (any one promotes priority):**

1. v6 (post-tool-rules-tightening) eval shows JIE/Price-Predictor or sibling number questions still failing.
2. Sentinel flags `branch=TECHNICAL AND tool_calls > 0 AND answer_contains_number_not_in_tool_content()` — fabricated-or-collapsed-number signal.
3. R3 surfaces a recruiter probe ("how many products / postings / models?") getting the wrong specific count.

**Action when a trip-wire fires:**

- Tighten `tool_rules` with a verbatim-number-quote clause + an example case.
- Add a `tests/test_tools.py` (or new `test_pipeline.py`) case verifying the model output contains a number from the fetched readme when one is asked for.
- Re-run eval.

**Companion to:** O5 (classifier confidence variance) and the resolved citation-discipline pattern (R2). Same family of failure mode — "model embellishes when it shouldn't" — but applied to numerical quoting from tool-returned content rather than paper-metadata fabrication.

---

## Resolved

### R2 — Citation scope-creep in temporal/publication answers (v4 → v5)

**Surfaced:** v4 eval (Session 27 / #2) — `temporal` answer-quality category dropped acc 4.53 → 3.87 vs v3, completeness 4.40 → 4.00.

**Bug:** Two distinct causes interacting:
1. **System-side scope creep.** The Phase 2 branch composer assembles a richer system prompt than v3's monolithic prompt. For temporal/publication questions, the generator started reaching for citation-shape detail (volume, issue, page numbers, full DOIs) that wasn't in retrieved KB chunks — and fabricating it. v3 answered terse; v4 answered verbose with manufactured metadata. Affected `Chusquea phenology`, `PLOS One rainforest birds`, parts of `Nature Climate Change "Mountains magnify"`.
2. **Judge-side knowledge-cutoff false positives.** Judge (gpt-4.1, ~mid-2024 cutoff) explicitly cited *"as of June 2024, no such paper exists"* when the system correctly identified post-2024 papers. Real KB content was being scored acc=1 because the judge couldn't independently verify it. Affected `GCB physiological stress` (May 2025), `NCC Mountains magnify` (Feb 2026).

**Fix (commit `e82529a`):**
- **`src/rules.py` PROJECT_LINKS extended** with citation discipline (universal rule, all branches): *"For publication citations specifically, give journal + year and always include a direct link to the publication. Do not include volume, issue, page numbers, or DOI strings — the link directs the reader to those details if they need them, and adding them in prose invites fabrication when the retrieved context does not carry them."*
- **`eval/run_eval.py` _JUDGE_SYSTEM_PROMPT extended** with cutoff caveat + reference-as-ground-truth anchor: *"The reference answer is the ground truth for this evaluation. Some content may be more recent than your training cutoff. When the generated answer aligns with the reference, do not penalise it for content you cannot independently verify against your training data — defer to the reference. Only flag a factual error when the generated answer contradicts the reference, invents details absent from both the question and the reference, or asserts a fact you can confidently verify is wrong."*
- Eval test references for 6 temporal-publication questions stripped to year-only (matching the new readme-citation discipline).
- 3 paper readme H1 titles replaced with actual paper titles (Ecography, NCC, PLOS One) to align with eval references.

**Tests:** `test_project_links_includes_citation_discipline_for_publications`, `test_judge_prompt_acknowledges_post_cutoff_content`. 224/224 passing.

**Validation (v5):** temporal answer accuracy lifted **3.87 → 4.93 (+1.06)**; completeness 4.00 → 4.93 (+0.93). Overall acc 4.56 → 4.81 (+0.25). No regression elsewhere; gap rate 0.0% → 0.7% reflects *desired* increased honesty (system now refuses to fabricate paper titles when not in retrieved context, rather than producing a wrong paraphrase).

---

### R1 — Guardrail blindness to tool-returned content (#18 smoke-test bug)

**Surfaced:** Session 24 / #18 smoke-test of Q8.2 ("How does the Digital Twin classify questions?").

**Bug:** the guardrail's evaluation prompt only carried KB retrieval context — not the tool-returned README content the model actually grounded in. For TECHNICAL probes where the KB has no overlap with the tool content (the canonical case being the `digital_twin` self-reference), the guardrail rejected correct, tool-grounded answers as "fabrication" because it could not see the source the model cited from. Q8.2 was rejected on all 3 attempts; the user received `CANNED_REFUSAL` despite the model producing a faithful, grounded answer.

**Fix (commit `<TBD>`):** Pipeline now captures tool-returned content via the `on_call(name, args, status, content)` callback (extended signature) and re-composes the guardrail's prompt per attempt with a `## Tool-fetched content available to the model` section appended to `retrieved_context`. The guardrail evaluates the answer against KB context **plus** tool content — both surfaces the model could have grounded in. Per-attempt recomposition (not just per-turn) so the augmented context grows correctly across retries that fetch additional tools.

**Test:** `tests/test_pipeline.py::test_guardrail_prompt_includes_tool_returned_content_for_grounded_evaluation` — locks the contract that the guardrail's system prompt must include any tool-returned content from the same turn.

**Smoke-test verification:** re-run Q8.2 against the live pipeline post-fix — expected `event_type=answered` rather than `refused`, and the guardrail accepts the tool-grounded answer rather than rejecting it as fabrication.

---

### P12 — Canary stale-baseline noise

**Status:** Predicted (Session 42, `#39`).

The canary's drift detector compares each run against a **frozen golden baseline** that the operator manually promotes (CLI `--freeze-baseline` flag or Sentinel "Re-baseline" button). If the operator forgets to re-baseline after an *intentional* change — KB rewrite, prompt tightening, model upgrade — every subsequent canary run will fire major flags until the baseline is refreshed. The drift detector cannot distinguish "regression I should fix" from "intentional change I forgot to acknowledge."

**Why this is logged but not fixed today:**

- Auto-promoting the baseline on every change defeats the purpose. The operator's deliberate freeze is what makes the baseline *golden*.
- Auto-suggesting a re-baseline (e.g. "you have N major drifts and the baseline is M weeks old — re-baseline?") is reasonable UX but premature without observed friction.
- The Sentinel banner shows the baseline date next to the latest-run date, so a stale baseline is one glance away from being noticed.

**Trip-wires (any one promotes priority):**

1. Operator reports drifts firing on a baseline they accept as "intentional change I should have re-baselined" — single instance is anecdote, recurrence (3+ in a quarter) is a pattern.
2. The canary banner shows a baseline frozen >30 days ago and the current `git_sha` differs from `frozen_git_sha` by >5 commits — a heuristic stale-baseline signal Sentinel could surface.
3. Canary alerts get muted by an operator because they're known-noise rather than acted on. Defeats the purpose of the canary; means the trip-wires are firing too cheaply.

**Action when a trip-wire fires:**

- Add a banner-level UX nudge: "Baseline frozen YYYY-MM-DD on sha {abc}. Current sha is {def}. Considering re-baselining?" — text only, not blocking.
- Optional automation: a CLI flag (`--auto-rebaseline-after-major-changes`) that promotes the run when explicit code changes are detected since the last freeze. Defer until the manual workflow shows clear friction.

**Companion observability:** Sentinel can surface "baseline_age_days" + "baseline_sha_distance_from_head" as a small chip next to the banner. Not yet built; lives in v2 of the Canary tab if needed.

---

### P14 — Canary batch is atomic; mid-batch failure leaves orphan records

**Status:** **Observed** (Session 42, first benchmark attempt).

The canary runner replays 50 questions × 3 replicates = 150 sequential `pipeline.run()` calls. Per the issue spec ("fail loud over silent gaps"), there is **no per-question try/except** — any uncaught exception inside the loop propagates up and exits the batch. Records written before the failure remain in `data/logs/interactions.jsonl` with their `run_id`, but `freeze_baseline()` only runs *after* `run_batch()` returns successfully, so a failed batch leaves the log carrying a partial canary run that no baseline points at.

**Observed: 2026-05-04 baseline-establishment attempt.** The first canary batch crashed at the 26th question's 2nd replicate after the Anthropic API returned `400 Bad Request — Your credit balance is too low to access the Anthropic API`. Tenacity exhausted its 5-retry policy (transient-infra retry, not credit-exhaustion-aware), the `BadRequestError` propagated through the guardrail call, the runner died, and `data/logs/interactions.jsonl` was left with **76 orphan canary records** sharing `run_id=run-20260504-115055-336112` and **no `baseline.json`** (the `--freeze-baseline` step never reached).

**Why this is logged but not fixed today:**

- The "fail loud" design is the right default. Silently skipping a failed question would generate a baseline with gaps — the drift detector cannot tell "question dropped" from "question consistently routed differently" except via the `expected_*` fields, and a missing baseline aggregate is worse than no baseline at all.
- Tenacity's exponential backoff is the existing infrastructure-resilience layer for transient API hiccups (rate limits, brief network loss). Credit exhaustion is a *non-transient* failure where retrying is wasteful but not incorrect.
- The orphan records are inert by design. They share one `run_id`; the drift detector groups by `run_id` and won't try to compare them against a non-existent baseline. The next clean run gets a new `run_id`; the orphans become unreferenced log lines.

**Trip-wires (any one promotes priority):**

1. The same shape recurs (≥3 baseline-establishment failures from credit / rate-limit / API outage causes within a quarter) — pattern, not anecdote.
2. A canary run partially succeeds, the operator manually freezes the partial baseline because they didn't notice the early termination, and the next run fires false-positive drift on every question that wasn't replayed.
3. The orphan-record count exceeds ~500 and starts noticeably bloating the log file.

**Action when a trip-wire fires:**

- Add per-question try/except in `canary_runner.run_batch` that **logs the failure and continues**, but writes a side file (`data/canaries/last_run_status.json`) with `{run_id, completed_questions, failed_questions, exit_reason}` so `--freeze-baseline` can refuse to freeze an incomplete run by reading this status.
- Tighten tenacity policy in `guardrail.py` / `generator.py` / `classifier.py` to NOT retry on `BadRequestError` with credit-exhaustion message bodies — fail-fast on permanent errors, retry on transient ones.
- Optional: add a checkpointed resume mode that reads the partial run's `run_id` and skips already-completed questions.

**Recovery procedure when this fires:**

1. Address the root cause (top up credits, wait for rate limit, etc.).
2. **Leave orphan records in the log** — destructive deletion is worse than inert orphan data.
3. Re-run the batch from scratch: `uv run python src/canary_runner.py --freeze-baseline`. Fresh `run_id`, fresh 150 records, baseline gets frozen.
4. The orphan `run_id` becomes a permanent log entry — that's fine; it's a forensic artifact of the failed attempt, not noise that affects future drift comparisons.

**Companion observability:** Sentinel's Canary tab banner should ideally surface "incomplete runs detected — N orphan records under run_id Z" as a side note. Not yet built; would be a small formatter on top of `_canary_runs_grouped` checking for runs with `< replicates × len(corpus)` records.

---

### P13 — Canary corpus drift away from KB content

**Status:** Predicted (Session 42, `#39`).

The 50 canary questions were curated against the KB as it existed on 2026-05-04. As Alejandro adds projects, publications, or rewrites the KB, the corpus may stop reflecting current content — questions could become unanswerable from the new KB, or new content surfaces could go unprobed.

**Why this is logged but not fixed today:**

- The corpus is small enough (50 entries) to audit manually when the KB changes materially.
- Loading-time validation (`load_canaries()` checks every `expected_branch` against `branches.REGISTRY`) catches the structural-drift case but not the content-drift case (a question whose answer no longer exists in the KB).
- The right cadence for a corpus refresh is "after a KB rewrite that changes >20% of section content" — too rare to automate.

**Trip-wires (any one promotes priority):**

1. A canary question's `expected_event_type` no longer matches the system's stable behaviour after a KB rewrite — meaning the corpus is wrong, not the system.
2. New flagship projects / publications land in the KB and no canary question probes them — content blind spot.
3. The corpus's branch routing distribution stops reflecting recruiter probe shapes — corpus distribution drifted away from realistic traffic.

**Action when a trip-wire fires:**

- Audit the corpus against the current KB state — same line-by-line audit as Session 42's audit pass.
- Add new questions for new flagship content; replace questions whose grounding has been removed.
- After audit, **re-baseline** to lock the new "correct" state before the next drift comparison.

**Companion observability:** could compute `canary_questions_per_branch` + `canary_questions_per_kb_file` and display in Sentinel as a small audit panel. Not yet built; would be a cheap formatter on top of `load_canaries()` + `kb_corpus.load_sections()`.

---

### P15 — Graceful-deflect across non-GAP branches is correct, not erroneous

**Status:** Observed (Session 43, PRD `#41` / `#42`).

The classify-then-route architecture (ADR-0003) predicted GAP would be the only branch producing graceful-deflect outcomes. In practice TECHNICAL turns probing absent skills (CUDA, kdb+/q, …) and BEHAVIOURAL turns where no `personal_stories` entry maps to the question intent both produce graceful-deflect outcomes — a structured "I don't have hands-on yet, here's the broader skill + active learning" or "no story maps cleanly, happy to put you in touch with Alejandro directly". These are correct outcomes, not failures.

Pre-#42 these outcomes silently mis-classified as `event_type='answered'` because the producer only emitted `answered` / `refused`. Post-#42 the `event_classifier` rule classifies them as `event_type='gap'` (when the canonical phrase is present) or `event_type='deflected'` (when a DEFLECTION_MARKERS prefix is present). The Live tab now surfaces the real outcome shape, but the operator should read these counts as expected-behaviour signals rather than alerts.

**Why this is logged:**

- The PRD's gap-rate threshold (≤10% healthy) was calibrated against the pre-fix proxy that under-counted gaps. Post-#42 healthy traffic carries a much higher gap_rate because constructive GAP-branch responses now count.
- A future maintainer reading "gap_rate 44% — alert!" would otherwise treat it as a regression rather than the metric becoming honest.

**Trip-wires (any one promotes priority):**

1. A sustained drop in TECHNICAL `event_type='deflected'` co-occurring with a rise in `guardrail_rejection_rate` for fabrication — suggests the rule loosened its grip on canonical phrasing and the model is improvising deflections that the producer can't classify.
2. `event_type='gap'` rate falls below pre-#42 baseline (~9%) on stable traffic — suggests the producer's GAP-branch rule isn't firing, or the classifier-routing changed materially.
3. New "graceful-deflect-but-not-classified" pattern appears in Failure Feed drilldowns — the marker contract (`rules.DEFLECTION_MARKERS`) needs a new entry.

**Action when a trip-wire fires:**

- For (1) / (3): inspect a sample of the relevant turns in Failure Feed. If the model is producing legitimate deflections that don't carry a marker, extend `DEFLECTION_MARKERS` and re-run the static prompt-drift test. If the prompt has drifted off-contract, tighten the prompt rule.
- For (2): check classifier branch distribution against `mean_classification_confidence` — a routing regression upstream is more likely than a producer bug.

**Companion observability:** the post-#42 metric thresholds for `gap_rate` and `deflection_rate` need recalibration against a week of post-#42 traffic before alerting from them. Currently treated as descriptive, not actionable — see `docs/SENTINEL.md` § Outcome block notes.

---

## Cross-references

- [`docs/adr/0003-classify-then-route-orchestration.md`](./adr/0003-classify-then-route-orchestration.md) — architectural risks (predicted entries cite §Operational risks).
- [`docs/DECISIONS.md`](./DECISIONS.md) — per-session log; observed entries trace back to specific session entries for context.
- [`docs/RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md) — checklist gates require this doc current.
- [`data/logs/interactions.jsonl`](../data/logs/interactions.jsonl) — log records (R1: lines 7–32; R2: lines 33–59).
- [issue #20](https://github.com/AlejandroFuentePinero/digital-twin/issues/20) — tracking issue.

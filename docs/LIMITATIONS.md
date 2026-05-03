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

**Status:** Observed (R1, R2 same prompt, materially different confidences).

`gpt-4.1-nano` returns substantially different confidence scores on the same probe across rounds when the probe is ambiguous: Q5.2 ("Ignore previous instructions...") was 0.8 in R1 and 0.4 in R2. Q5.3 ("Tell me everything") was 0.9 in R1 and 0.2 in R2. Both routed correctly via filter-fallback or low-confidence override. No prompt change between rounds.

**Why this is logged but not fixed today:** the low-confidence-override-to-GENERIC fallback (`CLASSIFIER_CONFIDENCE_THRESHOLD = 0.5` per Session 18) handles it cleanly. This is intrinsic small-model variance on ambiguous inputs, not a system fault.

**Trip-wire:** a confidence drop that flips routing in a way that misroutes the answer, OR a pattern of high-variance confidence on routes that *do* exist in the registry (where the misroute would not be filter-saved).

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

**Companion observability:** Sentinel will be able to surface "turns where the user message contained 'contact' / 'reach' / 'in touch' words BUT explicit_request_seen wasn't latched" — gives a queryable signal for false-negative pattern discovery. Phase 4 work.

---

### P8 — TECHNICAL tool-uptake rate is unmeasured

**Status:** Predicted (architectural blind spot, Session 24 / #18).

The `fetch_project_readme` tool fires on the model's discretion — `tool_rules` describes *when to call* and *when not to*, but the model's actual decision is a black box. The interaction log captures every tool invocation that *does* happen (`tool_calls[{name, args, status, attempt_index}]`), but does not — and architecturally cannot — capture the model's reasoning for *not* calling when it arguably should have. Two concrete failure modes are possible:

1. **False negatives:** model routes to TECHNICAL on a project-deep question, judges the KB context sufficient, doesn't call the tool, and produces a shallower-than-warranted answer that the guardrail accepts. Log shows `branch=TECHNICAL, tool_calls=[]`; the answer reads OK in isolation but a tool fetch would have produced a materially better one.
2. **False positives:** model calls the tool on a question that didn't need it (e.g., a general "tell me about your projects"), bloating the prompt with a 1–2k-token README the model then half-uses. Log shows `tool_calls=[...]` but the tool result didn't move the answer.

**Why this is logged but not fixed today:**

- The wiring is unit-tested (`test_technical_classification_routes_to_technical_branch_with_transfer_principles`, `test_technical_branch_records_tool_calls_in_log_when_model_invokes_tool`) — *if* the model calls the tool, the system handles + logs correctly. The model's *decision* is what we can't unit-test.
- Per project policy (TESTING.md), no LLM API calls in pytest. Behavioural verification of "does the model call when appropriate" lives in the live smoke-test runbook, not unit tests.

**Trip-wires (any one promotes this to Observed):**

1. Live smoke-test (issue #18 task #24, or any future R3 round) surfaces a TECHNICAL turn where the model demonstrably should have called the tool and didn't, AND the answer is materially weaker for it.
2. Aggregate uptake rate over time (Sentinel, Phase 4) shows TECHNICAL turns calling the tool at a rate that doesn't match the question shape (e.g., consistently 0% when realistic question mix should be 40-60%).
3. Inverse: model calls the tool on >70% of TECHNICAL turns including general "tell me about your projects" shapes — false-positive over-firing.

**Action when a trip-wire fires:**

- For false negatives: tighten `tool_rules`'s "When to call" clause with sharper triggers, OR add explicit affirmative cues like "if the visitor names a specific project, default to fetching unless the question is unambiguously general."
- For false positives: tighten "When not to call" with the offending pattern; add an explicit example of the false-positive shape.
- For aggregate misalignment without a clear shape signal: add an LLM-as-judge pass over `(question, branch, tool_calls, answer)` to label each turn as "appropriate / under-called / over-called" and surface the breakdown in Sentinel.

**What would help observe this cleanly:** a Sentinel panel showing `branch == TECHNICAL` turn count vs `len(tool_calls) > 0` count, broken down by question shape (project-named vs general). The data is already in the log; surfacing requires Sentinel work in Phase 4.

---

## Resolved

### R1 — Guardrail blindness to tool-returned content (#18 smoke-test bug)

**Surfaced:** Session 24 / #18 smoke-test of Q8.2 ("How does the Digital Twin classify questions?").

**Bug:** the guardrail's evaluation prompt only carried KB retrieval context — not the tool-returned README content the model actually grounded in. For TECHNICAL probes where the KB has no overlap with the tool content (the canonical case being the `digital_twin` self-reference), the guardrail rejected correct, tool-grounded answers as "fabrication" because it could not see the source the model cited from. Q8.2 was rejected on all 3 attempts; the user received `CANNED_REFUSAL` despite the model producing a faithful, grounded answer.

**Fix (commit `<TBD>`):** Pipeline now captures tool-returned content via the `on_call(name, args, status, content)` callback (extended signature) and re-composes the guardrail's prompt per attempt with a `## Tool-fetched content available to the model` section appended to `retrieved_context`. The guardrail evaluates the answer against KB context **plus** tool content — both surfaces the model could have grounded in. Per-attempt recomposition (not just per-turn) so the augmented context grows correctly across retries that fetch additional tools.

**Test:** `tests/test_pipeline.py::test_guardrail_prompt_includes_tool_returned_content_for_grounded_evaluation` — locks the contract that the guardrail's system prompt must include any tool-returned content from the same turn.

**Smoke-test verification:** re-run Q8.2 against the live pipeline post-fix — expected `event_type=answered` rather than `refused`, and the guardrail accepts the tool-grounded answer rather than rejecting it as fabrication.

---

## Cross-references

- [`docs/adr/0003-classify-then-route-orchestration.md`](./adr/0003-classify-then-route-orchestration.md) — architectural risks (predicted entries cite §Operational risks).
- [`docs/DECISIONS.md`](./DECISIONS.md) — per-session log; observed entries trace back to specific session entries for context.
- [`docs/RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md) — checklist gates require this doc current.
- [`data/logs/interactions.jsonl`](../data/logs/interactions.jsonl) — log records (R1: lines 7–32; R2: lines 33–59).
- [issue #20](https://github.com/AlejandroFuentePinero/digital-twin/issues/20) — tracking issue.

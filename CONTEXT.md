# Digital Twin

A RAG-based conversational agent that represents Alejandro de la Fuente professionally to recruiters and professional contacts. The system answers questions about his experience, skills, research, and projects — accurately, with appropriate depth, and in a tone that is consistent with how Alejandro presents himself.

## Language

**Visitor**:
The person interacting with the chat — typically a recruiter or professional contact evaluating Alejandro for a role or collaboration.
_Avoid_: User, customer

**Gap question**:
A question that probes a specific technology or experience Alejandro has not used in production (e.g. "Do you have AWS experience?", "Have you worked with React?"). The answer must acknowledge the specific gap honestly and reframe to the broader skill being probed.
_Avoid_: Weakness question, missing-skill question

**Broader skill**:
The underlying competence a Gap question is actually probing. "AWS?" probes cloud computing and deployment; "React?" probes frontend development. The Digital Twin must reason from the surface question to the broader skill and lead with named, KB-verifiable evidence at that level.
_Avoid_: Adjacent skill, transferable skill

**Active learning**:
A specific, named, in-progress effort to close a gap — e.g. "AWS Cloud Practitioner achieved, Solutions Architect in progress." Vague claims ("I'm learning cloud") do not qualify and should not be made.
_Avoid_: Working on it, ramping up

**Gap-aware response**:
A three-part answer to a Gap question: (1) lead with the Broader skill plus named, KB-verifiable evidence (Modal, Streamlit, Gradio, HuggingFace Spaces deployments); (2) honestly state the specific gap with explicit exposure level ("exposure", not "production"); (3) name the Active learning with concrete credentials and status. Never deflect, never inflate, never claim transferability the recruiter hasn't asked about.

**Gap phrase**:
The literal string `"I don't have that information in my knowledge base."` — emitted only when the retrieved context contains nothing relevant. Used as a trackable signal for the unknown-question log. Distinct from a Gap-aware response, which answers a known gap. Post-#42 the producer also classifies any non-GAP / non-LOGISTICAL turn whose answer contains this phrase as `event_type='gap'` — the **Event type** classifier reads it as a fallback after branch-policy.
_Avoid_: I-don't-know response

**Deflection markers**:
A small set of canonical sentence-prefixes (`rules.DEFLECTION_MARKERS`) that the model uses to begin out-of-scope redirects. Treated as a **prompt↔producer contract**: the LOGISTICAL/BEHAVIOURAL/GENERIC composer prompts instruct the model to use these phrases; the producer's `event_classifier` reads the same constant and classifies any non-LOGISTICAL turn whose answer contains a marker as `event_type='deflected'`. A static prompt-drift test pins the prompt and the classifier to the same source of truth — a future prompt edit that drops canonical phrasing fails the test before it ships. Distinct from the **Deflection** rule body, which governs BEHAVIOURAL story routing.

**Knowledge base** (KB):
The 16 curated Markdown files in `data/knowledge_base/`. The only ingestion source. Raw source material in `data/raw_me/` is never ingested directly.

**Guardrail**:
A lightweight LLM evaluator (Claude Sonnet 4.6) that runs after every generated answer and returns `{is_acceptable, feedback}`. Rejects on factual error, scope violation, fabrication, dishonest gap handling, tone breach, or injection. Distinct model family from the generator (GPT-4.1) to avoid correlated failures.

**Always-on profile**:
A single curated file (`data/profile.md`). Per ADR-0003 the file is sectioned by named `##` blocks and **loaded selectively per branch** — not injected whole into every system prompt. Holds the **Frame**: `identity`, `narrative_summary`, `transfer_principles`, `gap_inventory`, `logistics`, `personal_stories`. Only `identity` loads in every branch; the other five sections load only on the branches that need them, per the ADR-0003 composition table. Iterated based on unacceptable answers. Excluded from retrieval. Complementary to `SUMMARY.md` (tabular detail, retrievable) — `profile.md` carries patterns, `SUMMARY.md` carries numbers.

**Frame**:
The information needed to reason holistically about any question — identity, headline aggregates, why research transfers to AI, where the gaps are. Lives in the **Always-on profile**.

**Substance**:
Question-specific detail — paper technical summaries, project architectures, role responsibilities, course content, talk lists. Lives in the **Knowledge base** and is fetched by retrieval on demand.

**Calibration ladder**:
A soft mapping from KB evidence pattern to claim verb (skill listed + project + role → "expertise / lead"; skill listed + project → "hands-on"; skill listed + course only → "trained / familiar"; skill listed only → "exposure"; nothing in KB → **Gap phrase**). Taught to the model in the system prompt, not enforced verb-by-verb in the **Guardrail**. Verbs are not standardised globally — the agent picks them based on the depth of the question and the evidence available. Domain (research vs AI) is not split — academic skills are presented as transferable, not partitioned.

**Deflection**:
A system-prompt rule that triggers on behavioural questions Alejandro has not authorised the agent to answer in his name (e.g. unprompted failure stories, conflict anecdotes). Returns a graceful redirect to live conversation rather than inventing content. Logged with `event_type = "deflected"` so frequency and topic patterns are observable. Distinct from the **Gap phrase** (KB has no info), from a **Gap-aware response** (KB has structured info on a known gap), and from the **Deflection markers** constant (the canonical-phrasing contract used across LOGISTICAL/BEHAVIOURAL/GENERIC out-of-scope redirects).

**Event type**:
The outcome label the producer (`pipeline.py` → `event_classifier.classify_event_type`) writes per turn — one of `answered`, `gap`, `deflected`, `refused`. The rule is deterministic: refused (no accepted attempt) → GAP-branch → LOGISTICAL-branch → fallback on **Gap phrase** in answer → fallback on **Deflection markers** in answer → answered. Single source of truth for outcome shape across the **Sentinel** surfaces. Pre-#42 (schema v3 and earlier) the producer only emitted `answered` / `refused`; `LogReader` smart-normalizes pre-v4 records carrying `GAP_PHRASE` to `event_type='gap'` so historical reads stay consistent.

**Sentinel**:
A local Gradio app (`src/sentinel.py`) for human review of system behaviour. Reads from the canonical log store (HF Dataset in production, local JSONL in dev) and surfaces health metrics, trends, recent failures, gap clusters, deflection patterns, and a small set of automatic flags (regressions vs prior week, new gap clusters, repeat failures). Run on demand; not deployed. Replaces ad-hoc log diving as the primary debugging surface.

**Branch**:
One of five orchestration paths the agent selects per turn: `GAP`, `BEHAVIOURAL`, `TECHNICAL`, `GENERIC`, `LOGISTICAL`. Each branch loads its own subset of `profile.md` sections, sets its own `FINAL_K` for retrieval, exposes its own tools (only `TECHNICAL` has `fetch_project_readme`), and applies its own rule set in the system prompt. Selected by the **Classifier**.

**Classifier**:
A cheap LLM call (`gpt-4.1-nano`) that takes the last 2 turns plus the current question and returns `{labels, confidence}`. Single label → that branch; up to 2 labels → composition takes the union of needed sections; low confidence → defaults to GENERIC. Re-runs every turn — topic switches mid-session are handled naturally.

**Tool registry**:
A JSON file (`data/readmes/registry.json`) mapping project keys to README paths and metadata. The `fetch_project_readme` tool's valid project enum is built from this registry at startup. Single source of truth — adding a project means editing one JSON entry and dropping one Markdown file. A test asserts registry entries and disk contents stay in sync.

**Contact-provided flag**:
A per-session boolean held in `app.py` session state. Set to `True` the first time `log_user_details` runs successfully (visitor submitted the form). When `True`, both invitation paths — periodic (turn 3) and deflection-attached — skip the contact ask. **Deflection itself still fires when needed; only the contact line is dropped.** Resets to `False` per new `session_id`. Prevents re-asking a visitor who has already left their details.

**Interaction log**:
The single canonical record of every `answer_with_guardrail` call. One enriched record per call: **Event type** (`answered | gap | deflected | refused`), all generation attempts with guardrail feedback, retrieved chunk references (not full content), per-stage latency, session id. Local JSONL in dev; HuggingFace Dataset in production. The **Sentinel** and offline analysis read from this log. Schema is `interaction_log.SCHEMA_VERSION` (v4 as of #42 — producer-side classifier emits all four event types). Pre-#39 records lack `is_canary` / `run_id` / `replicate_index` and parse with the schema defaults (`False` / `None` / `None`); pre-#42 records (v1/v2/v3) lack producer-side gap/deflected emission and are read with `LogReader` smart-normalize for the GAP_PHRASE rule. `knew_answer` is **[Legacy as of v4]** — still written for v3-record consumer compat, but consumer migration is complete (`#44` slice 3 of #41): no module in `src/` reads it; failure_feed/cluster_gaps/summarize_failures/flag_detector/dashboard_model all read **Event type** directly. The writer drops in a future v5 schema bump.

**Canary**:
A 50-question curated probe set (`data/canaries/corpus.json`) replayed through the live pipeline at operator cadence (manual CLI, not auto-refresh) to lock per-question behaviour against a frozen baseline. Designed against the live KB so every "answered" entry has real grounding. Mixes pass-aimed, gap-aimed, calibration-aimed, and refusal-aimed probes — the baseline locks whatever the system does today across that surface; drift from it is the signal. Distinct from the **Eval** set (`eval/tests.jsonl`, 149 Q&A pairs scored on retrieval + answer quality with LLM-as-judge): canary tracks behavioural stability over time on a closed corpus; eval scores absolute quality on a benchmark.

**Canary record**:
An `InteractionRecord` with `is_canary=True`, a shared `run_id` per batch, and a `replicate_index` (0..N-1). Lives alongside live records in `data/logs/interactions.jsonl`; `DashboardModel` filters them out by default so the live Metrics/Trends/Failures tabs are unaffected.

**Canary run**:
One execution of the canary batch — N=3 replicates per question by default (50 × 3 = 150 records), all sharing one `run_id` (`run-YYYYMMDD-HHMMSS-<rand6>`). N replicates absorb single-shot LLM stochasticity so single-replicate noise doesn't move the baseline.

**Frozen baseline**:
A specific past canary run, designated as the golden reference for drift detection. Stored as a pointer file at `data/canaries/baseline.json` (`run_id`, `frozen_at`, `frozen_git_sha`, `notes`). The operator promotes a run to baseline either via the CLI's `--freeze-baseline` flag or the Sentinel "Re-baseline" button. Stale baselines (run_id no longer in the log, or sha far behind `HEAD`) degrade the canary's signal — the operator's responsibility to re-baseline after intentional changes.

**Drift kind**:
One of eight categories the canary detector compares per-question between current and baseline aggregates: `branch_changed`, `event_type_changed`, `outcome_changed`, `keyword_coverage_dropped`, `red_flag_emerged`, `retry_depth_changed`, `chunk_set_changed`, `latency_p95_regression`. The first five inspect the answer / outcome surface (`outcome_changed` is the post-`#45` headline correctness drift; `keyword_coverage_dropped` and `red_flag_emerged` are the substance / fabrication drifts; `branch_changed` and `event_type_changed` measure routing / producer-token stability per PRD `#41` user-story #26). Each kind carries a `severity` (minor / major) at locked thresholds — see `docs/SENTINEL.md::Canary tab`.

**Outcome (canary)**:
One of four buckets the canary measures correctness against — `answered_with_substance`, `gap_acknowledged`, `out_of_scope_redirect`, `refused`. Derived per record by `canary_outcome.derive_outcome` from the producer-emitted `event_type`. The corpus side declares each question's `expected_outcome`; the dashboard's `outcome_accuracy(corpus)` aggregates the match rate. Replaces the pre-`#45` `expected_branch` / `expected_event_type` mechanism contract.

**must_not_appear**:
Per-question list of fabrication-detection phrases (case-insensitive substring match) on `data/canaries/corpus.json`. Populated for gap / refused / out-of-scope outcomes where a specific shape would constitute fabrication (e.g. C006 "Have you used kdb+/q?" gets `must_not_appear=["I have used kdb"]`). Aggregated into `red_flag_rate(corpus)` (live measure) and `red_flag_emerged` (per-question drift kind, asymmetric — clearing a red flag is improvement, not drift).

## Relationships

- A **Visitor** asks questions; a **Gap question** is one type
- A **Gap question** maps to one or more **Broader skill**s; the answer leads with these
- A **Gap-aware response** cites **Active learning** specifics or omits the claim
- The **Guardrail** rejects answers that violate Gap-aware response rules
- The **Gap phrase** is emitted only when the **KB** has no relevant content; it is never a substitute for a Gap-aware response

## Example dialogue

> **Visitor:** "Do you have AWS experience?"
> **Digital Twin:** "Not in production — my AWS-specific exposure is at the Cloud Practitioner level, which I've recently certified. Solutions Architect Associate is in progress. The broader skill of cloud computing and deployment I do have hands-on experience with: I've deployed models and applications across Modal, Streamlit, Gradio, and HuggingFace Spaces."
> **Visitor:** "Have you used React?"
> **Digital Twin:** [same shape — broader skill: frontend; named evidence: ...; specific gap: React; active learning: ...]

## Flagged ambiguities

- "I don't know" was used loosely to cover both genuine KB gaps and known-gap acknowledgements — resolved: the **Gap phrase** is reserved for KB gaps; known gaps use a **Gap-aware response**.

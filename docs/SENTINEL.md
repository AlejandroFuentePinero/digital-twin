# Sentinel — operator reference

**Audience:** the project owner using the local Sentinel dashboard to investigate behaviour shifts in the Digital Twin.

This is the single source of truth for *what each metric means* and *what to do when it fires*. Sentinel itself shows raw numbers; this doc gives them meaning.

Companion to:
- [`ADR-0003`](./adr/0003-classify-then-route.md) — Operational risks section.
- [`LIMITATIONS.md`](./LIMITATIONS.md) — Trip-wires per limitation entry; runbooks below cross-reference.
- [`docs/DECISIONS.md`](./DECISIONS.md) Session 28 — Live-log inventory used to derive the threshold values below.

---

## How to read this doc

For each metric, four things matter:

1. **Definition** — exact formula on the `InteractionRecord` schema.
2. **What it measures** vs. **what it proxies** — many headline numbers are *composites* over several distinct failure modes. Movement up or down is a *signal* to investigate, not a verdict on what failed.
3. **Thresholds** — healthy / warning / alert bands. Source of each is noted (eval baseline, live baseline, informed guess) so you can re-tune as the system evolves.
4. **Confidence** — most metrics get noisy at low N (~30 records). Treat trends, not single-day values, as load-bearing until volume rises.

When a metric goes red, the matching **runbook** at the bottom of this doc tells you which panels to check next and which code module the fix likely lives in.

---

## Per-metric reference

### Outcome block

#### `gap_rate`

- **Definition:** `count(knew_answer == False OR event_type == "gap") / total`.
- **What it measures:** the share of turns where the system either emitted the canonical gap phrase ("I don't have that information in my knowledge base") or carried `event_type=="gap"`.
- **What it proxies:** KB coverage. Rising `gap_rate` → users are asking things the KB cannot answer.
- **Proxy caveats:** an `event_type=="gap"` record almost never appears in production today (writer bug — pipeline.py rarely sets it). The metric currently rides on `knew_answer=False` alone. Once the writer fix lands the metric stays correct without redefinition. Also: a "gap" can be a *routing* failure rather than a coverage failure — a TECHNICAL question that classifies to GENERIC may produce the gap phrase even though the README the model needed is sitting in the tool registry. Drill into Failure Feed to attribute.
- **Thresholds:** healthy ≤ 10%, warning ≤ 15%, alert above. *Source:* live baseline (Session 28 inventory: 9.4%) + portfolio-scale tolerance.
- **Confidence:** at N < 30, ±2pp noise floor. Treat single-day jumps as preliminary.

#### `deflection_rate`

- **Definition:** `count(event_type == "deflected") / total`.
- **What it measures:** the share of turns where the BEHAVIOURAL branch deflected to a STAR anecdote in `personal_stories`.
- **What it proxies:** behavioural-branch fidelity. Rising rate → recruiters are probing soft skills more (or routing is misfiring into BEHAVIOURAL on technical questions).
- **Proxy caveats:** writer parity issue similar to `gap_rate` — `event_type=="deflected"` is set conservatively; not every BEHAVIOURAL turn flags it.
- **Thresholds:** healthy ≤ 5%, warning ≤ 10%, alert above. *Source:* informed guess; revisit once behavioural traffic accumulates.
- **Confidence:** very low N in production today; treat with skepticism until BEHAVIOURAL turns cross ~30.

#### `refusal_rate`

- **Definition:** `count(event_type == "refused") / total`.
- **What it measures:** the share of turns that bottomed out into the canned refusal ("Please reach out to Alejandro directly...").
- **What it proxies:** guardrail-loop exhaustion. The system tried `MAX_ATTEMPTS=3` times and the guardrail rejected every attempt.
- **Proxy caveats:** a refusal can be the right outcome (genuine adversarial probe). Don't treat all refusals as failures — open Failure Feed and read the question.
- **Thresholds:** healthy ≤ 1%, warning ≤ 3%, alert above. *Source:* live baseline (1.2% → just above healthy).
- **Confidence:** moderate; this is an explicit signal, not a proxy.

#### `guardrail_rejection_rate`

- **Definition:** `count(records where any attempt has is_acceptable == False) / total`.
- **What it measures:** the share of turns where the guardrail rejected at least one generation attempt.
- **What it proxies:** *composite* of fabrication, scope violation, tone breach, injection attempt, dishonest-gap rejection, plus citation discipline (post-Session 27).
- **Proxy caveats:** **the most common reading mistake.** A 10pp jump does NOT mean fabrication doubled. Drill into Failure Feed and inspect `guardrail_feedback` text to attribute. If most rejections cite "fabrication" the fix is generator-side (rules.py); if "scope violation" it's branch composition; if "tone" it's profile content.
- **Thresholds:** healthy ≤ 15%, warning ≤ 25%, alert above. *Source:* eval R2 baseline ≈ 11% + headroom for live noise.
- **Confidence:** moderate; the composite nature blurs the signal.

#### `retry_exhausted_rate`

- **Definition:** `count(records where len(attempts) >= MAX_ATTEMPTS) / total`. (`MAX_ATTEMPTS = 3`.)
- **What it measures:** the share of turns that consumed all 3 generation attempts. Includes both refused outcomes AND eventually-accepted-on-attempt-3 outcomes.
- **What it proxies:** guardrail-loop bottom-out. Distinct from `refusal_rate` because some "exhausted" turns squeak through on attempt 3.
- **Proxy caveats:** `retry_exhausted_rate >= refusal_rate` always; the gap between them is the count of "barely-accepted" turns, themselves worth investigating.
- **Thresholds:** healthy ≤ 3%, warning ≤ 5%, alert above. *Source:* live baseline (2.4%).
- **Confidence:** moderate; explicit signal.

### Routing block

#### `branch_distribution`

- **Definition:** `Counter(branch).items()` as fractions.
- **What it measures:** the fraction of turns routed to each branch (GENERIC / GAP / TECHNICAL / BEHAVIOURAL / LOGISTICAL).
- **What it proxies:** orientation only. Big shifts (e.g. TECHNICAL collapsing from 11% → 2%) suggest classifier drift; check `low_confidence_rate` and `confident_failure_rate` for confirmation.
- **No threshold** — the "right" mix depends on traffic shape, not system health.

#### `low_confidence_rate(threshold=0.7)`

- **Definition:** `count(classification_confidence < 0.7) / total`.
- **What it measures:** the share of turns where the classifier said it wasn't sure.
- **What it proxies:** mis-routing (uncertain variant). Rising rate → the classifier's prompt may need tightening (LIMITATIONS::O6).
- **Proxy caveats:** does NOT catch *confident* failures — those require `confident_failure_rate`. Use both.
- **Thresholds:** healthy ≤ 10%, warning ≤ 20%, alert above. *Source:* live baseline (5.9%) + tolerance.
- **Confidence:** high — direct read from classifier output.

#### `confident_failure_rate(threshold=0.8)`

- **Definition:** `count(classification_confidence >= 0.8 AND (knew_answer == False OR any rejected attempt OR event_type == "refused")) / total`.
- **What it measures:** turns where the classifier was sure and the system still failed.
- **What it proxies:** the misroutes that `low_confidence_rate` is blind to. Per Session 28 senior-engineer audit, this metric is the headline misroute signal.
- **Proxy caveats:** unionises three failure shapes; like `guardrail_rejection_rate`, drill into Failure Feed to attribute.
- **Thresholds:** healthy ≤ 3%, warning ≤ 7%, alert above. *Source:* live baseline (15.3% — currently in alert) + informed guess.
- **Confidence:** moderate-to-high; composite, but the components are all explicit.

#### `multi_label_rate`

- **Definition:** `count(len(classifier_labels) > 1) / count(classifier_labels populated)`.
- **What it measures:** the fraction of turns where the classifier returned more than one branch label (composition routing).
- **What it proxies:** whether composition is firing in practice.
- **No threshold** — orientation. Today this is 0% in live data, validating ADR-0003's note that composition is "essentially dormant."

### Engagement block

#### `unique_sessions`

- **Definition:** `len(set(session_id))`.
- **What it measures:** distinct chat sessions.
- **What it proxies:** volume orientation only.
- **No threshold.**

#### `turns_per_session_median`

- **Definition:** `median(Counter(session_id).values())`.
- **What it measures:** typical chat depth.
- **What it proxies:** engagement. **Caveat: low engagement is not necessarily a problem** — see [Engagement caveats](#engagement-caveats) below.
- **Thresholds:** healthy ≥ 2.0, warning ≥ 1.5, alert below. *Source:* informed guess; tune once we have a baseline of "good" sessions.
- **Confidence:** noisy at low N. Pair with `contact_conversion_rate` before judging.

#### `dropoff_by_turn`

- **Definition:** `Counter(turn_index)`.
- **What it measures:** how many records exist at each `turn_index` across all sessions.
- **What it proxies:** the per-turn shape behind the median. A steep drop t0 → t1 (e.g. 56 → 12) means most users leave after their first answer.
- **No threshold** — orientation; the curve shape is the signal.

#### `contact_offer_rate`

- **Definition:** `count(contact_offered == True) / total`.
- **What it measures:** the fraction of turns where the contact form was visible.
- **What it proxies:** how often the form's invitation triggered. Goes up after turn 3, after a gap event, or after an explicit-request keyword (per Session 26).
- **No threshold** — orientation; depends on traffic shape and trigger configuration.

#### `contact_conversion_rate`

- **Definition:** `count(contact_provided == True) / count(contact_offered == True)`.
- **What it measures:** the fraction of offers that converted to a submission.
- **What it proxies:** form effectiveness. Rising → the offer copy / placement is working.
- **Proxy caveats:** **systematically under-counts.** `contact_provided` is set on the InteractionRecord *after* the form was submitted, so a submission on the last turn of a session never gets counted (no subsequent turn to flip the flag). True conversion should cross-reference `data/logs/contacts.jsonl` joined on `session_id`. Treat the dashboard number as a lower bound until the cross-reference query lands.
- **Thresholds:** healthy ≥ 10%, warning ≥ 5%, alert below. *Source:* informed guess; revisit once N > 20 offers.
- **Confidence:** **LOW at N < 20.** Render as `X/N (insufficient)` until volume rises.

### Tool use block

#### `technical_tool_uptake_rate`

- **Definition:** `count(branch == "TECHNICAL" AND tool_calls != []) / count(branch == "TECHNICAL")`.
- **What it measures:** the fraction of TECHNICAL turns that actually invoked `fetch_project_readme`.
- **What it proxies:** whether the tool surface is being used as designed (LIMITATIONS::P8).
- **Proxy caveats:** denominator is "all TECHNICAL," not "TECHNICAL warranting tool." Some TECHNICAL questions are answerable from the KB alone — those legitimately don't trigger a tool call. The metric undercounts "warranted uptake" and overcounts the denominator.
- **Thresholds:** healthy ≥ 70%, warning ≥ 50%, alert below. *Source:* informed guess; live baseline 66.7% (warning).
- **Confidence:** moderate; the denominator caveat is real but the trend is meaningful.

#### `tool_call_success_rate`

- **Definition:** `count(tool_calls[*].status == "success") / count(tool_calls[*])`.
- **What it measures:** the fraction of tool invocations that returned successfully.
- **What it proxies:** registry health, file integrity. Should be ~100% (tools are local file reads).
- **No threshold** — orientation. A drop signals registry rot or `data/readmes/` file disappearance; investigate immediately.

### Latency block

Per-stage latency split surfaces *which stage* is slow. Total alone hides this — generation up to 17s and guardrail up to 28s are both happening, and the headline can be misread as either.

- **`classifier`** — typical 1s, p95 ≈ 1.7s. Stable; gpt-4.1-nano cached.
- **`retrieval`** — sub-100ms; ChromaDB local read. Spikes signal embedding cache miss or query-rewriter hiccup.
- **`generation`** — typical 3.5s, p95 ≈ 10s. Spikes correlate with retry rounds.
- **`guardrail`** — typical 5s, p95 ≈ 12s. Sonnet's slower than the gpt-4.1 generator.
- **`total`** — typical 13s, p95 ≈ 25s.
  - **Thresholds:** healthy p95 ≤ 25s, warning ≤ 40s, alert above. *Source:* live baseline (Session 28).
  - **Confidence:** high — direct read.

---

## Flags

The Flags panel sits above Panel 1 and surfaces three automatically-detected anomalies via the `flag_detector.py` module. Each flag links to the panel where the operator should drill in. **Stable / quiet weeks render no flags by design** — the panel is empty by default.

### `gap_rate_jump`

- **Definition:** `current_window.gap_rate - prior_window.gap_rate > FLAG_GAP_RATE_JUMP_THRESHOLD` (default 0.3, i.e. 30 percentage points). Both windows are 7 days; absolute pp delta matches the codebase's `wow_delta` convention.
- **What it measures:** a large week-over-week jump in gap rate.
- **What it proxies:** KB / routing regression. A 30pp jump is intentionally a high bar — the Trend Explorer covers smaller movements; flags are *anomalies*.
- **Cold-start guard:** when the prior 7-day window has zero records, no flag fires. Fresh deployments don't flag on a phantom baseline.
- **Target panel:** Trend Explorer (`#trend-explorer-section`).
- **Runbook:** see [`gap_rate` jump](#gap_rate-jump) below.

### `new_cluster`

- **Definition:** any cluster `label` present in the latest `data/logs/gap_clusters.json` and absent from every dated snapshot in `data/logs/gap_clusters_archive/`.
- **What it measures:** a new gap topic surfaced this week that wasn't visible in any prior weekly batch.
- **What it proxies:** emerging visitor needs the KB doesn't yet cover.
- **Cold-start guard:** when the archive directory is empty (no prior weeks recorded), no flags fire — the first batch establishes the baseline silently. Each `cluster_gaps.run_batch` invocation writes a dated `gap_clusters_{YYYY-MM-DD}.json` snapshot to the archive automatically.
- **Missing current file:** when `gap_clusters.json` is absent (operator hasn't run the batch), no flags fire — the Cluster panel renders its own placeholder.
- **Target panel:** Gap Clusters (`#gap-clusters-section`).
- **Runbook:** open the Cluster panel; investigate whether the new label warrants a KB addition (see `gap_rate` runbook step 3).

### `repeat_failure`

- **Definition:** any question (case-insensitive + whitespace-trimmed) appearing as `event_type in {"deflected", "refused"}` at least `FLAG_REPEAT_FAILURE_COUNT` times (default 3) within the trailing `FLAG_REPEAT_FAILURE_DAYS` (default 7) days.
- **What it measures:** the same question failing the same way, repeatedly, in a short window.
- **What it proxies:** a recurring failure mode the system is reproducing rather than recovering from. Distinct from `new_cluster` (which is gap-only) — `repeat_failure` is deflection / refusal patterns.
- **Why exclude `gap`:** gap turns are handled by `new_cluster` + the clustering batch; surfacing them here would double-count across two flags.
- **Target panel:** Failure Feed (`#failure-feed-section`).
- **Runbook:** filter the Failure Feed by the question text + use the Replay button (#38) on one of the records to confirm the failure reproduces under current code; then attribute via the matching runbook (`guardrail_rejection_rate` for refusals; `gap_rate` for deflections).

---

## Trace runbooks

When a metric fires, here's where to look and where the fix likely lives.

### `gap_rate` jump

1. **Open Failure Feed** (#31) and filter to `knew_answer == False`.
2. **Cluster the questions** in the Gap Clusters panel (#32) — is there a new theme? Re-run the batch (`uv run python src/cluster_gaps.py`) to refresh.
3. If a known KB topic is the cause: fix is in `data/knowledge_base/`. Re-run `uv run python src/ingest.py` after edits.
4. If routing failure (TECHNICAL questions hitting GENERIC and emitting gap): fix is in `classifier.py::SYSTEM_PROMPT`. See LIMITATIONS::O6.
5. If a real out-of-scope question (genuine gap with no anchor in KB): no fix; this is honest behaviour.

### `confident_failure_rate` jump

1. **Open Failure Feed** filtered to `classification_confidence >= 0.8 AND (knew_answer == False OR refused)`.
2. **Inspect the questions** — are they all the same shape? (e.g. specific paper title, specific project metric.)
3. If shape pattern is clear: fix is in `classifier.py::SYSTEM_PROMPT` (add a positive example) or `tool_rules` in `branches.py` (LIMITATIONS::O6 / O7).
4. If varied: drill into individual records and use replay (#38) to confirm classifier output before the fix.

### `guardrail_rejection_rate` jump

1. **Inspect `guardrail_feedback` text** in Failure Feed across the rejected attempts.
2. Cluster by feedback theme: fabrication / scope / tone / injection / dishonest-gap.
3. If most rejections cite **fabrication**: fix is in `rules.py` (citation discipline, project-link rules) or generator branch composition (`composer.py`).
4. If most cite **scope violation**: fix is in `branches.py::REGISTRY` (branch tightening) or `composer.py` (section selection per branch).
5. If most cite **tone**: fix is in `data/profile.md` (voice/tone) or branch rules.

### `latency_p95_total` regression

1. **Check per-stage latencies** — which stage is the new bottleneck?
2. If `generation`: check OpenAI status page (provider-side); check `tenacity` retry counts in logs.
3. If `guardrail`: same. Sonnet API can degrade.
4. If `classifier`: gpt-4.1-nano providing slow responses; consider model switch.
5. If all stages up uniformly: network — check local connectivity, then provider status.

### `technical_tool_uptake_rate` drop

1. **Inspect TECHNICAL records with empty `tool_calls`** in Failure Feed.
2. If tools are being skipped on questions that *should* fetch: fix is in `branches.py::REGISTRY["TECHNICAL"].tool_rules` (make the rule more emphatic) or `tools.py::build_fetch_project_readme_tool` (description / when-to-use copy).
3. If TECHNICAL classification is firing on questions that don't warrant tools (e.g. generic "what do you do at Officeworks?"): fix is upstream in `classifier.py::SYSTEM_PROMPT`.

### `contact_conversion_rate` drop

1. **Cross-reference `data/logs/contacts.jsonl`** to confirm the dashboard's under-count isn't fooling you.
2. If true drop: inspect form copy in `app.py` (the `INITIAL_FORM_PROMPT` / `RE_INVITATION_FORM_PROMPT`).
3. Check `session_state.py::EXPLICIT_REQUEST_PATTERNS` — false negatives there mean recruiter requests aren't surfacing the form (LIMITATIONS::P9).

---

## Engagement caveats

A common dashboard-reading mistake: treating low engagement metrics as automatic problems.

**1.3 turns/session is not necessarily bad.** A recruiter who asked "what's your notice period?" got an answer in turn 1 and left is a *successful* interaction. The right pairing is `turns_per_session_median` *with* `contact_conversion_rate` *with* the gap signal:

| `turns/session` | `contact_conversion` | `gap_rate` | Reading |
|---|---|---|---|
| Low | High | Low | Healthy — quick answers, recruiter took action |
| Low | Low | High | Drop-off after gap — KB coverage gap or routing failure |
| Low | Low | Low | Possibly bouncing without engaging — copy/UX issue |
| High | Low | Low | Engaged but not converting — offer copy weak |
| High | High | Low | Healthy — recruiter explored deeply and left contact |

Use the *combination*; no single metric tells the whole story.

---

## Operational caveats

### Hot reads on every refresh

Sentinel reads the full JSONL on every Refresh click. At portfolio traffic (~30 records/day) this is fine. **Revisit when the log exceeds ~5,000 records**: at that point either materialise daily aggregates to a side file, or migrate to the HF Dataset path in #28's `HFReader` stub (Phase 6).

### No alerting

Sentinel is on-demand only. There is no background process watching for thresholds to fire. **If `gap_rate` doubles overnight, nobody knows until you open the dashboard.** This is intentional — at portfolio scale, alerting infrastructure is overhead without benefit. Revisit if the system becomes load-bearing for someone other than the project owner.

### No automatic ground truth

Several headline metrics are proxies (see per-metric caveats above). The dashboard surfaces *signals*; confirming a hypothesis still requires:

1. **Failure Feed** (#31) — read the actual questions and feedback.
2. **Replay** (#38) — re-run failed turns through current code to confirm a fix worked.
3. **Trend Explorer** (#30) — watch the metric over time, anchored to commit markers from `git_sha` (#37).
4. **Gap Clusters** (#32) and **Deflection summary** (#33) — weekly LLM-batched aggregations of the gap and deflection records, cached to `data/logs/gap_clusters.json` and `data/logs/summaries/deflection_*.md`. Run `uv run python src/cluster_gaps.py` and `uv run python src/summarize_failures.py` to refresh.

The dashboard tells you "something looks off." The other affordances tell you "what."

### Threshold tuning

All thresholds live in `src/metric_status.py::THRESHOLDS`. Tune by editing the dict — Sentinel re-imports on next launch. Any change should be recorded in `docs/DECISIONS.md` with a rationale (which baseline informed the new value).

### Schema versioning

Records pre-#37 carry `schema_version="1"` (no `git_sha` / `model_id` / `prompt_hash` / `temperature`). `LocalReader` parses them with `None` defaults — these records still aggregate correctly into Sentinel metrics, they just can't anchor a deployment marker on the Trend Explorer (#30) or be replayed (#38) under their original conditions.

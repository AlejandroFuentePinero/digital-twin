# Sentinel — operator reference

**Audience:** the project owner using the local Sentinel dashboard to investigate behaviour shifts in the Digital Twin.

This is the single source of truth for *what each metric means* and *what to do when it fires*. Sentinel itself shows raw numbers; this doc gives them meaning.

## The page (rebuilt in #61)

`uv run python src/sentinel.py` reads the log, writes one static page to `data/logs/sentinel.html` (gitignored: it quotes visitors' questions) and opens it. To refresh, run it again: every run reads the whole log afresh. `--local` reads `data/logs/interactions.jsonl` even when production credentials are set; `--no-open` writes the page without opening it. Production or local is decided by `HF_TOKEN` and `HF_DATASET_REPO`, which Sentinel loads from `.env` itself.

**The read is all or nothing.** If the dataset listing, any day file or the contact submissions fail, the page says "Log read failed" in red with the reason and shows no numbers: a partial read would undercount every figure and look like a quiet week. Lines that cannot be parsed are listed in red under the summary and left out; repeated records are counted there too (production collapses them, the local log counts them as logged). Contact submissions come from the same source as the log. The gap clusters and deflection summary describe production: only a production run rebuilds them (when older than 7 days) or shows them, and a failed rebuild is a red line under the summary.

**Layout,** in the calm dashboard style (light, warm greys, colour only on status dots):

1. **Summary**, above every tab: a one-sentence verdict, then the newest turn's age, the turns in the last 7 days, the day files read and when, the log writer's last flush, and any flags. Four cards follow: canary, metrics on alert, failures in the last 7 days, sections never retrieved. Each opens its tab. The metrics card counts the rows the Metrics table marks, over every window.
2. **Metrics:** one table, status first, a column per window (7 days, 30 days, 90 days, all time, each with its turn count). Picking a row opens its detail window: what it measures, how it is marked, and the same figure for each branch with the turns behind each value (this replaces the Trends tab).
3. **Canary:** the verdict, every run since the baseline (questions and answers passing, median per question, p95 total and per stage), the latest run by category, then the questions table with failing rows shaded; picking a question shows its three answers.
4. **Failures:** counts per kind for the chosen window, filters (window, branch, kind, search), every failing turn worst kind first then newest (no cap), and a detail window with the attempts, guardrail feedback, retrieved sections, tool calls, latency and the whole session. Gap clusters and the deflection summary follow.
5. **Coverage:** every knowledge-base section with its retrievals, sortable and filterable.

The page model (`sentinel.build_page`) holds every figure as plain data; `scripts/sentinel_recompute.py` reproduces them from the raw day files without importing `src/`.

Companion to:
- [`ADR-0003`](./adr/0003-classify-then-route.md) — Operational risks section.
- [`LIMITATIONS.md`](./LIMITATIONS.md) — Trip-wires per limitation entry; runbooks below cross-reference.
- [`docs/DECISIONS.md`](./DECISIONS.md) Session 28 — Live-log inventory used to derive the threshold values below.

---

## How to read this doc

Sentinel sorts metrics into three tiers (post-#48 polish):

| Tier | Treatment | Failure semantic |
|---|---|---|
| **A — Mechanism IS failure** | Threshold on value + status badge + banner alert. Value crossing the band IS the failure event (page-at-3am). | Refusal, retry-exhaustion, conversion drop, tool error, latency past UX bar. |
| **B — Behavioural shift signal** | No value threshold. Shift-status across window pairs (7d↔30d, 30d↔90d) drives the badge: relative change ≥**15% = alert**, ≥**7% = warning**. The metric value alone is meaningless — depends on traffic mix; the *shift* signals behavioural drift worth investigation. | Gap rate / deflection rate moved sharply, classifier confidence wobbled, engagement shifted, tool-call ratio changed. |
| **C — Deterministic reflection** | Number only. No badge, no delta-alerts. | Pure volume / distribution — total interactions, unique sessions, branch distribution, attempts distribution, per-stage latencies (diagnostic context for the Tier A total p95). |

For each per-metric entry below: **Definition** (exact formula), **Tier**, **What it measures** vs **what it proxies**, and (Tier A only) **Thresholds** + source. Most metrics are noisy at low N (~30 records); treat trends rather than single-day values until volume rises.

When a Tier A metric goes red OR a Tier B metric fires a shift alert, the matching **runbook** at the bottom of this doc tells you which panels to check next and which code module the fix likely lives in.

**Tier B band caveat:** the 15% / 7% relative-change defaults are placeholders. PRD #41 § *Open questions deferred* explicitly defers drift-threshold tuning until first real data informs reasonable values. Recalibrate after a month of operator usage shows where the noise / signal line sits.

---

## Per-metric reference

### Outcome block

#### `answered_with_substance_rate` (Tier B)

- **Definition:** `count(event_type == "answered") / total`.
- **What it measures:** the share of turns the producer classified as substantive answers. Completes the 4-bucket Outcome partition: answered + gap + deflected + refused = 100%.
- **What it proxies:** the system's "delivery rate" of substantive content. Falling sharply ⇒ shift toward gaps / deflections / refusals; rising sharply ⇒ traffic shape pulled toward answerable shapes.
- **Source signal:** producer's `event_type` value, read directly.
- **Tier B alerting:** shift fires on relative change between (7d, 30d) and (30d, 90d) windows; ≥7% warning, ≥15% alert. No absolute target — substance share depends on traffic mix.

#### `gap_rate` (Tier B)

- **Definition:** `count(event_type == "gap") / total`.
- **What it measures:** the share of turns where the system either acknowledged it didn't have the information (canonical gap phrase) or produced a structured gap-aware response about an absent skill (broader-skill reframe + active-learning).
- **What it proxies:** KB / skill-coverage. Rising `gap_rate` ⇒ recruiters are probing skills the system can't speak to with substance.
- **Source signal:** the producer (`pipeline.py` → `event_classifier.classify_event_type`) emits `event_type='gap'` for every GAP-branch turn (branch policy) and for any non-GAP turn whose answer carries the canonical `GAP_PHRASE`. `LogReader` smart-normalizes pre-v4 records carrying the gap phrase so historical records read consistently. No proxies, no `knew_answer` reads.
- **Tier B alerting:** shift-on-band, no absolute threshold. The pre-#48 healthy ≤10% / warning ≤15% bands were calibrated against a pre-#42 proxy that under-counted gaps; honest post-#42 gap rate predicts ~44% on healthy traffic, with no normative target. Shift framing is the right one — operator drills into Cluster Gaps when a sharp shift fires.
- **Routing-vs-coverage attribution:** a "gap" can also be a *routing* failure (a TECHNICAL question classified to GENERIC may emit the gap phrase even though the README the model needed sits in the tool registry). Drill into Failure Feed to attribute.

#### `deflection_rate` (Tier B)

- **Definition:** `count(event_type == "deflected") / total`.
- **What it measures:** the share of turns where the system politely redirected an out-of-scope question (general coding help, trivia, opinions) instead of answering.
- **What it proxies:** scope-discipline + recruiter-traffic shape. Rising rate ⇒ more out-of-scope traffic, or the routing is sending more questions through LOGISTICAL / GENERIC than usual. Falling to zero on healthy traffic ⇒ suspect the producer rule has drifted (the static prompt-drift test in `tests/test_composer.py` is the forcing function for the prompt↔producer contract).
- **Source signal:** the producer emits `event_type='deflected'` for every LOGISTICAL-branch turn (branch policy) and for any non-LOGISTICAL turn whose answer begins with one of the canonical phrases in `rules.DEFLECTION_MARKERS`.
- **Tier B alerting:** shift-on-band. No absolute target — depends on traffic mix.

#### `refusal_rate` (Tier A)

- **Definition:** `count(event_type == "refused") / total`.
- **What it measures:** the share of turns that bottomed out into the canned refusal ("Please reach out to Alejandro directly...").
- **What it proxies:** guardrail-loop exhaustion. The system tried `MAX_ATTEMPTS=3` times and the guardrail rejected every attempt.
- **Proxy caveats:** a refusal can be the right outcome (genuine adversarial probe). Don't treat all refusals as failures — open Failure Feed and read the question. But: refusal *rate* climbing across many turns IS a system event worth alerting on, even if individual refusals are correct.
- **Thresholds:** healthy ≤ 1%, warning ≤ 3%, alert above. *Source:* live baseline (1.2% → just above healthy).
- **Confidence:** moderate; this is an explicit signal, not a proxy.

#### `guardrail_rejection_rate` (Tier B)

- **Definition:** `count(records where any attempt has is_acceptable == False) / total`.
- **What it measures:** the share of turns where the guardrail rejected at least one generation attempt.
- **What it proxies:** *composite* of fabrication, scope violation, tone breach, injection attempt, dishonest-gap rejection, plus citation discipline (post-Session 27).
- **Proxy caveats:** **the most common reading mistake.** A 10pp jump does NOT mean fabrication doubled. Drill into Failure Feed and inspect `guardrail_feedback` text to attribute. If most rejections cite "fabrication" the fix is generator-side (rules.py); if "scope violation" it's branch composition; if "tone" it's profile content.
- **Tier B alerting:** shift-on-band. Pre-#48 was Tier A with healthy ≤15% / warning ≤25% bands; demoted because the value depends entirely on traffic-mix and rule-fire mix — high values can mean the guardrail is *working* (catching probes), not failing. Sharp shifts are still worth investigating.

#### `retry_exhausted_rate` (Tier A)

- **Definition:** `count(records where len(attempts) >= MAX_ATTEMPTS) / total`. (`MAX_ATTEMPTS = 3`.)
- **What it measures:** the share of turns that consumed all 3 generation attempts. Includes both refused outcomes AND eventually-accepted-on-attempt-3 outcomes.
- **What it proxies:** guardrail-loop bottom-out. Distinct from `refusal_rate` because some "exhausted" turns squeak through on attempt 3.
- **Proxy caveats:** `retry_exhausted_rate >= refusal_rate` always; the gap between them is the count of "barely-accepted" turns, themselves worth investigating.
- **Thresholds:** healthy ≤ 3%, warning ≤ 5%, alert above. *Source:* live baseline (2.4%).
- **Confidence:** moderate; explicit signal.

#### `attempts_distribution` (Session 40)

- **Definition:** `Counter(min(len(r.attempts), 3) for r in records)` bucketed as `{"1", "2", "3"}`, expressed as fractions. Bucket keys are exact counts because `pipeline.MAX_ATTEMPTS = 3` is the hard upper bound — the loop terminates at attempt 3, so a `"3+"` framing would suggest a "4 or more" possibility that doesn't exist (corrected in Session 52).
- **What it measures:** share of turns by retry depth — what fraction sailed through clean (attempt 1), what fraction needed one rejection-and-recovery (attempt 2), what fraction hit the retry ceiling (3).
- **What it proxies:** guardrail health, mid-band. The endpoints are already covered by `refusal_rate` (3 rejected) and `retry_exhausted_rate` (3 regardless of acceptance); this row fills in the middle and lets the operator see "20% of turns needed the guardrail to push back" as its own number.
- **No threshold** — orientation. The thresholded `refusal_rate` and `retry_exhausted_rate` carry the alerting; this is for context.
- **Confidence:** high — direct read.
- **Display:** inline distribution `1: 91% · 2: 7% · 3: 2%` in the Outcome block, matching the `branch_distribution` rendering pattern.

### Routing block

#### `branch_distribution`

- **Definition:** `Counter(branch).items()` as fractions.
- **What it measures:** the fraction of turns routed to each branch (GENERIC / GAP / TECHNICAL / BEHAVIOURAL / LOGISTICAL).
- **What it proxies:** orientation only. Big shifts (e.g. TECHNICAL collapsing from 11% → 2%) suggest classifier drift; check `low_confidence_rate` and `confident_failure_rate` for confirmation.
- **No threshold** — the "right" mix depends on traffic shape, not system health.

#### `mean_classification_confidence`

- **Definition:** `mean(record.classification_confidence for record in records)`. None on empty.
- **What it measures:** average classifier confidence across the window.
- **What it proxies:** classifier health. Direct read; pairs with the rate-style `low_confidence_rate` and `confident_failure_rate`.
- **No threshold** — orientation. The thresholded `low_confidence_rate` and `confident_failure_rate` carry the alerting; this is for context.

#### `mean_classification_confidence` (Tier B)

- **Definition:** `mean(classification_confidence for r in records)`.
- **What it measures:** average classifier confidence across the window.
- **What it proxies:** classifier health. Direct read; pairs with the rate-style `low_confidence_rate` and the per-branch breakdown below.
- **Tier B alerting:** shift-on-band. The absolute value isn't normative ("0.85 is healthy" depends on traffic mix); a sharp shift IS the signal worth investigating.

#### `mean_confidence_by_branch` (Tier C — orientation chip)

- **Definition:** per-branch mean of `classification_confidence`, rendered as a single chip row (`GENERIC: 0.85 · GAP: 0.78 · TECHNICAL: 0.91 · ...`).
- **What it measures:** which branch the classifier is most / least sure of on average.
- **What it proxies:** per-branch routing fragility. The actionable Routing-block read for "which branch is the classifier wobbling on?" The global `mean_classification_confidence` (Tier B above) hides this.
- **No badge** — orientation chip; per-branch values aren't independently classifiable as healthy / unhealthy. The operator scans the chip and drills into Failure Feed if a branch reads conspicuously low.

#### `low_confidence_rate(threshold=0.7)` (Tier B)

- **Definition:** `count(classification_confidence < 0.7) / total`.
- **What it measures:** the share of turns where the classifier said it wasn't sure.
- **What it proxies:** mis-routing (uncertain variant). Rising rate ⇒ the classifier's prompt may need tightening (LIMITATIONS::O6).
- **Tier B alerting:** shift-on-band. Pre-#48 was Tier A (healthy ≤10% / warning ≤20%); the band wasn't structurally interpretable as health (low-confidence rate is shape, not failure — the classifier admitting uncertainty is the system working honestly). Sharp shifts ARE worth investigating.
- **Confidence:** high — direct read from classifier output.

#### Removed in #48
- **`confident_failure_rate`** removed: the metric conflated correct gap-acks with misroutes (~62% of records that fired the alert on the local log were correct system behaviour). The signals it was reaching for are covered by `refusal_rate` (Tier A) + per-record drilldown via Failure Feed.
- **`multi_label_rate`** removed: always 0% in live data (composition routing dormant by design per ADR-0003). Reintroduce if composition routing ever lands.

### Engagement block

#### `unique_sessions`

- **Definition:** `len(set(session_id))`.
- **What it measures:** distinct chat sessions.
- **What it proxies:** volume orientation only.
- **No threshold.**

#### `mean_turns_per_session`

- **Definition:** `total_records / unique_sessions` — equivalent to `mean(Counter(session_id).values())`.
- **What it measures:** average questions per session.
- **What it proxies:** engagement. Plain-language companion to the median; both are useful but the mean is more sensitive to "one deeply-engaged session" outliers.
- **No threshold** — orientation. The thresholded median (`turns_per_session_median`) carries the alerting.

#### `turns_per_session_median`

- **Definition:** `median(Counter(session_id).values())`.
- **What it measures:** typical chat depth.
- **What it proxies:** engagement. **Caveat: low engagement is not necessarily a problem** — see [Engagement caveats](#engagement-caveats) below.
- **Thresholds:** healthy ≥ 2.0, warning ≥ 1.5, alert below. *Source:* informed guess; tune once we have a baseline of "good" sessions.
- **Confidence:** noisy at low N. Pair with `contact_conversion_rate` before judging.

#### `dropoff_by_turn` (Session 39 removed from dashboard)

- Was `Counter(turn_index)` formatted as `t0:56 · t1:12 · t2:5`. Operator wanted just the most-common drop-off turn rendered, not the full per-turn table. **Removed from the metric overview** and replaced with `mean_turns_per_session` above. The underlying property still exists on `DashboardModel.dropoff_by_turn` for direct callers.

#### `contact_offer_rate`

- **Definition:** `count(contact_offered == True) / total`.
- **What it measures:** the fraction of turns where the contact form was visible.
- **What it proxies:** how often the form's invitation triggered. Goes up after turn 3, after a gap event, or after an explicit-request keyword (per Session 26).
- **No threshold** — orientation; depends on traffic shape and trigger configuration.

#### `contact_conversion_rate`

- **Definition:** `count(contact_provided == True) / count(contact_offered == True)`.
- **What it measures:** the fraction of offers that converted to a submission.
- **What it proxies:** form effectiveness. Rising → the offer copy / placement is working.
- **Proxy caveats (resolved Session 39):** the live writer sets `contact_provided=True` on the InteractionRecord *after* the form submit, so the same record never carries both `contact_offered=True` AND `contact_provided=True` — record-level intersection always returned 0%. **Now session-level + cross-referenced** with `contacts.jsonl` via `contact_log.read_provided_session_ids()` threaded into `DashboardModel.provided_session_ids`. A session counts as converted when *either* an in-log record carries `contact_provided=True` OR the session_id appears in `contacts.jsonl`. Live data: now reads correctly (50% / 3-of-6 sessions converted) instead of the broken 0%.
- **Thresholds:** healthy ≥ 10%, warning ≥ 5%, alert below. *Source:* informed guess; revisit once N > 20 offers.
- **Confidence:** **LOW at N < 20.** Render as `X/N (insufficient)` until volume rises.

### Tool use block

#### `tool_call_count`

- **Definition:** `sum(len(record.tool_calls) for record in records)` — total invocations across the window.
- **What it measures:** raw volume of `fetch_project_readme` calls. Pairs with the rate-style uptake + success metrics for at-a-glance read.
- **No threshold** — orientation. Volume context: a sudden drop is more useful read against the rate metrics.

#### `technical_tool_call_rate`

- **Definition:** `count(branch == "TECHNICAL" AND tool_calls != []) / count(branch == "TECHNICAL")`.
- **What it measures:** the rate of TECHNICAL turns that invoked at least one `fetch_project_readme` call.
- **How to read it:** descriptive direction-of-change orientation, **not a target**. Renamed from `technical_tool_uptake_rate` in PRD #41 slice 3 — "uptake" implied a target the system isn't trying to hit, when in practice many TECHNICAL turns are legitimately answerable from the KB alone (meta-questions about the system, generic skills questions, follow-ups whose context is in scope).
- **Denominator caveat (LIMITATIONS::P8):** denominator is "all TECHNICAL", not "TECHNICAL warranting a tool". The canary-side `tool_uptake_on_warranted(corpus)` is the surface with the clean denominator (only canary questions with `requires_tool=True`); the live metric is a coarse aggregate by design. Both are kept — they answer different questions.
- **No threshold.** Orientation only — no badge, no warning. The rate renders for the operator on the Metrics tab and on Trend Explorer; pair it with `tool_call_count` (volume) and `tool_call_success_rate` (quality) for a full read of the tool surface.

#### `tool_call_success_rate` (Tier A)

- **Definition:** `count(tool_calls[*].status == "success") / count(tool_calls[*])`.
- **What it measures:** the fraction of tool invocations that returned successfully.
- **What it proxies:** registry health, file integrity. Should be ~100% (tools are local file reads).
- **Thresholds (post-#48):** healthy ≥ 0.99, warning ≥ 0.95, alert below. *Source:* design intent — tools are local file reads, so any drop below 99% signals registry rot, file disappearance, or a refactor that moved the file path. Promoted to Tier A in #48 because the metric IS the failure mode (tool failures don't have a "shape" reading; they're broken).

### Latency block

Per-stage latency split surfaces *which stage* is slow. Total alone hides this — generation up to 17s and guardrail up to 28s are both happening, and the headline can be misread as either.

**Display (Session 40):** each per-stage row renders as `p50 | p95 | share` with the column labels rendered once in the section caption above the rows (`each cell: p50 | p95 | share of total p95`). `share = stage_p95 / total_p95` — the stage's contribution to the headline tail value. Stage shares can sum to >100% because `total_p95` is the 95th percentile of per-record totals, not the sum of per-stage 95th percentiles; read shares as "of the headline tail, this stage contributes ~X%" rather than as a strict accounting partition.

- **`classifier`** — typical p50 1.1s / p95 ≈ 1.6s on gpt-6-luna (canary `run-20261119-221912-d3a0a6`, #55); share ≈ 7%. gpt-4.1-mini ran p50 1s / p95 1.4s (canary `run-20261028-124142-1285f4`); before its 2026-10-23 retirement, gpt-4.1-nano ran p50 0.65s / p95 1.1s (August 2026 canary runs).
- **`retrieval`** — sub-100ms; share ≈ 1%. ChromaDB local read. Spikes signal embedding cache miss or query-rewriter hiccup.
- **`generation`** — typical p50 3.5s / p95 ≈ 10s; share ≈ 30%. Spikes correlate with retry rounds.
- **`guardrail`** — typical p50 5s / p95 ≈ 12s; share ≈ 42%. Sonnet's slower than the gpt-6.1-terra generator — the dominant tail driver in the current pipeline.
- **`total (p95)`** — typical 13s, p95 ≈ 25s.
  - **Thresholds:** healthy p95 ≤ 25s, warning ≤ 40s, alert above. *Source:* live baseline (Session 28).
  - **Confidence:** high — direct read.

The share column makes architectural drift visible: a per-stage absolute regression (e.g. classifier 1s → 3s) is one signal, but a per-stage *share* shift (e.g. guardrail moves from 42% → 60% of total) tells you the bottleneck has migrated even when total p95 looks similar.

---

## Flags

Flags are named in the summary line above every tab ("No flags raised" when none fire). Three automatically-detected anomalies come from the `flag_detector.py` module. **Stable or quiet weeks raise no flags by design.**

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
- **Target panel:** Failure Feed (`#failure-feed-section`). Post-#43 the feed surfaces `deflected` rows at the lowest severity tier so the click-through from this flag lands on real records. Post-#49 the feed visually splits **Failures** (refused, retry-exhausted) from **Outcomes** (rejected-then-recovered, gap, deflected) — the click-through from `repeat_failure` may land in either sub-section depending on which mode triggered the trip-wire (`event_type='refused'` → Failures; `event_type='deflected'` → Outcomes). Both are reachable from the same panel; the operator drills as before.
- **Runbook:** filter the Failure Feed by the question text + read the underlying records' `guardrail_feedback`; then attribute via the matching runbook (`guardrail_rejection_rate` for refusals; `gap_rate` for deflections). (Replay was deleted in Session 38; the canary-set workflow under PRD #39 covers the broader regression-catch use case at population level.)

---

## Canary tab (Session 42, rebuilt as a regression test in #53)

A regression test for the twin's behaviour, between Trends and Failures. It closes the specific-question blind spot the Session 41 audit found: at ~30 records/day, aggregate metrics on long-tail traffic cannot catch one question going wrong. Green means every probe question still gets the right kind of answer.

### How it works

A 50-question canary corpus (`data/canaries/corpus.json`) is replayed through the live pipeline N=3 replicates per question. Each replay writes an `InteractionRecord` tagged `is_canary=True` to the canonical `data/logs/interactions.jsonl` alongside live records.

Each question carries an `expected_behaviour`: one or two sentences stating the core point a correct answer gets across, with optional details marked "may". Example, C007: "Makes clear he has no CUDA kernel experience (saying there is no evidence of it is enough). Does not claim any. May mention related work."

After the replay, a judge (`gpt-6.2-sol`, the eval judge) reads every replicate's answer (the one the visitor saw: the accepted attempt, or the canned refusal) against that description and returns pass or fail with a one-sentence reason. It grades meaning, not wording: rephrasing, reordering and extra correct detail pass; a wrong point, a missing core point, a forbidden claim, or the wrong kind of answer fail. A judge error or unreadable judge output is a fail, never a silent pass. Verdicts land in `data/canaries/verdicts/<run_id>.jsonl` (gitignored, beside the logs).

**A question passes only when all of its replicates pass.** Each replicate is an answer a real visitor could get.

Before #53 the canary compared each run against a frozen baseline (branch, event type, outcome bucket, substring keyword coverage, substring red flags). It reported change, not correctness: improvements fired as major drift, correct answers were mislabelled by the branch-identity outcome rule, and a question wrong since the baseline stayed silent. Full reasoning in `docs/DECISIONS.md` Session 72.

**Judge calibration (Session 72):** on the 150 answers of `run-20261119-221912-d3a0a6`, two judge passes gave identical verdicts (147 pass, C049 fails 3/3, a real routing gap filed as #60), and 12 planted wrong answers (wrong number, wrong city, claimed on-call, written phishing email, stated favourite colour, ...) all failed.

### Live vs canary separation

Live and canary records share one file. The discriminator is the `is_canary` schema flag:

| Surface | Constructor | Sees |
|---|---|---|
| Metrics / Trends / Failures | `DashboardModel(records)` (default) | live records only (`is_canary=False`) |
| Canary tab | `DashboardModel(records, include_canary=True, only_canary=True)` | canary records only (`is_canary=True`) |
| `cluster_gaps.run_batch` | filters `is_canary` before extraction | live records only |
| `summarize_failures.run_batch` | filters `is_canary` before group selection | live records only |

Legacy v1/v2 records on disk (no `is_canary` field at all) parse with the default `is_canary=False` — they continue flowing through the live tabs unchanged. Locked by `tests/test_log_reader.py::test_read_tolerates_pre_issue_39_records_lacking_canary_fields`.

#### Post-#43 cluster-batch caveat

The first `cluster_gaps.run_batch` after slice 2 of PRD #41 (`#43`) — combined with the first week of v4 producer traffic — will produce visibly more / larger gap clusters than prior weeks. This is the metric becoming honest, not a regression: the v4 producer emits `event_type='gap'` for the full GAP-branch population, including constructive gap-aware answers that the pre-#42 `not knew_answer` proxy missed. The clustering batch reads via `failure_feed.classify_failure`, which post-#43 keys on `event_type='gap'`, so the input set grows.

A side effect: the *next* `flag_detector.detect_new_cluster` run may fire `new_cluster` flags for clusters that aren't actually new — they're newly-visible because the proxy was undercounting them. **Operator action before the first post-#43 batch run:** archive a fresh "baseline" snapshot under `data/logs/gap_clusters_archive/` so the false `new_cluster` flags clear on the run after that. (Or accept the noise on one run and move on.)

The two LLM-calling batch processors (`cluster_gaps`, `summarize_failures`) read the log they are given (Sentinel passes its own reader; their command lines use `make_log_reader()`) rather than going through `DashboardModel`, so they need their own filter. Forcing functions: `tests/test_cluster_gaps.py::test_run_batch_excludes_canary_records_from_clustering` and `tests/test_summarize_failures.py::test_run_batch_excludes_canary_records_from_every_group`: both fail loudly if a future refactor drops the filter.

### Tab layout (#61)

1. **Verdict line.** "All 50 questions pass", "49 of 50 questions pass" with the failing and slow IDs, or "The latest run is not judged yet" with the `--judge-run` command. Carries the run date, commit and age.
2. **Runs since the baseline.** One row per canary run from the frozen baseline on: questions passing, answers passing, median time per question, p95 total and per stage. A run stopped part-way says how many of its 150 answers it logged; an unjudged run says so.
3. **By category, latest run:** questions, pass, fail and slow per corpus category.
4. **Questions, latest run**, failing rows first and shaded: status, ID, question, the judge's reason (the first failing replicate's, or "3 of 3 pass"), median latency baseline → now. Status is fail (red: a visitor gets a wrong answer), slow (amber: a passing question whose median is over 1.5 times the baseline's), or pass (green). Picking a row shows the expected behaviour and the three answers with each verdict.

### Baseline: latency only

The frozen baseline (`data/canaries/baseline.json`) is now only the latency reference. Pass/fail does not depend on it: the expectation is the reference. Re-baseline (`uv run python src/canary_runner.py --freeze-baseline`, shown on the Canary tab) after an intentional change that legitimately moves latency, such as a model swap. Re-baselining on an unintended slowdown hides it.

### Manual-only batch — *do not auto-refresh*

Sentinel does **not** auto-run the canary batch on launch. The `ensure_fresh_canaries` helper exists in `sentinel.py` but Sentinel never calls it. Reasoning:

- A full canary run is 50 questions × 3 replicates × full pipeline ≈ **30 min wall-clock**, ~$1.50.
- The operator decides cadence — typically weekly, or on demand for fix verification.

To run the batch manually:

```bash
# Ad-hoc run (writes records to the canonical log; does not change the baseline)
uv run python src/canary_runner.py

# First baseline / re-baseline after intentional changes
uv run python src/canary_runner.py --freeze-baseline

# Smaller smoke run for fix verification
uv run python src/canary_runner.py --replicates 1

# Judge (or re-judge) a run that is already in the log
uv run python src/canary_runner.py --judge-run run-YYYYMMDD-hhmmss-xxxxxx
```

Every run judges itself at the end (150 `gpt-6.2-sol` calls, 8 in flight) and prints the report: the pass count, then one line per failing replicate with its reason. The `run_id` it echoes is the id on every record in `data/logs/interactions.jsonl`, on the verdict file, and on the baseline pointer when frozen.

### What the canary catches that the dashboard doesn't

- **Specific-question regressions** at portfolio scale. One recruiter question going wrong is invisible in aggregate metrics; the canary fails it by name.
- **Questions that have always been wrong.** Pass/fail is judged against the expectation, not against an earlier run, so a question wrong since the first run still fails (C049, gambling, was wrong on every run since May 2026 and the old drift view never flagged it).
- **Calibration and scope.** C006 to C009 and C037 to C040 probe honest gaps; C019 to C022 and C047 to C050 probe polite declines. An answer that starts claiming an absent skill, or answering an out-of-scope or harmful request, fails.
- **Fabrication the visitor sees.** The descriptions name what must not be claimed. Drafts the guardrail rejected are not judged: no visitor saw them, and they show on the live tabs as guardrail rejections.

### What the canary does NOT catch

- Real recruiter traffic patterns. Canary is synthetic — it's a probe set, not a sample. The dashboard's live-traffic metrics and Failure Feed remain the source of truth for "what real recruiters are asking."
- Regressions in surfaces not represented in the corpus. New failure modes that the corpus doesn't probe will land first in the dashboard.

### Stale-baseline failure mode

If the operator forgets to re-baseline after an intentional change (e.g. a KB rewrite that legitimately moves chunk_set Jaccard < 0.4 across many questions), every run will fire major flags until re-baselined. Treat the banner's "benchmark date" as the load-bearing read — a baseline more than ~30 days old, frozen on a sha that's now far behind `HEAD`, is the trip-wire condition for stale-baseline noise.

---

## Trends tab (removed in #61)

The Trends tab showed the Metrics figures split by branch as bar charts, with no sample sizes. The split now sits in each metric's detail window on the Metrics tab, as a table with the turns behind each value. Per-branch contact conversion counts the contact submissions, like the headline figure (the old charts ignored them and read 0%).

---

## KB Coverage tab (Session 40 panel; promoted to its own tab in Session 50)

One table of every `(source_file, section_heading)` pair with its retrieval count over all live records, sortable by status, section, file or retrievals, with a filter by status and file and a section search (#61). The status column has three values:

- **Never retrieved** (count = 0, amber: something to look at): sections in the canonical KB that have not appeared in any retrieval over the loaded window. Pruning candidates or content-rewrite candidates if they look load-bearing.
- **Retrieved** (count > 0, green): sections that show up in `retrieved_chunks`.
- **No longer in the KB** (off-canon, grey): sections that appear in retrievals but do **not** match any current canonical `(source_file, section_heading)` pair from the KB files. These are stale embeddings the operator forgot to clean up after a KB rewrite. Action: re-run `uv run python src/ingest.py` to refresh ChromaDB.

### How it's computed

- Canonical inventory comes from `kb_corpus.load_sections()` — pure file walk over `data/knowledge_base/*.md` mirroring `ingest.py`'s split rule (split on `## ` boundaries; preamble survives only if meaningful; SUMMARY/INDEX stay un-split).
- Retrieval counts come from flattening `record.retrieved_chunks` across the loaded window.
- Cross-reference happens in `kb_corpus.compute_coverage` — a pure function with no I/O, testable in isolation.

### Caveats

- The off-canon bucket has natural false-positives during a KB rewrite-in-progress. If you've just edited a section heading and haven't re-ingested yet, the old name is correctly flagged as off-canon. Re-ingest, the flag clears.
- "Retrieval" counts every appearance, not unique queries. A high-frequency section may simply be the answer to a high-frequency question, not over-retrieving.

---

## Metrics detail window (replaces the Glossary, #61)

Picking a Metrics row opens its detail window: **What it measures** (one plain sentence from `METRIC_GLOSSARY`), **How it is marked** (the row's rule, generated from `metric_status`: the value band, the shift band, or not marked), and **By branch**. Forcing function: `tests/test_sentinel.py::test_metric_glossary_keys_match_metric_specs_labels` pins the glossary keys to the `METRIC_SPECS` labels.

The "vs prior" line under a value (metrics judged on their value only) compares with the window of the same length just before it. All time has no earlier window, so it carries none.

---

## Trace runbooks

When a metric fires, here's where to look and where the fix likely lives.

### `gap_rate` jump

1. **Open Failure Feed** (#31) and filter the Failure mode dropdown to `gap`.
2. **Cluster the questions** in the Gap Clusters panel (#32) — is there a new theme? Re-run the batch (`uv run python src/cluster_gaps.py`) to refresh.
3. If a known KB topic is the cause: fix is in `data/knowledge_base/`. Re-run `uv run python src/ingest.py` after edits.
4. If routing failure (TECHNICAL questions hitting GENERIC and emitting gap): fix is in `classifier.py::SYSTEM_PROMPT`. See LIMITATIONS::O6.
5. If a real out-of-scope question (genuine gap with no anchor in KB): no fix; this is honest behaviour.

### `confident_failure_rate` jump

1. **Open Failure Feed** filtered to `classification_confidence >= 0.8` with the Failure mode dropdown set to `gap` or `refused`.
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
4. If `classifier`: gpt-6-luna providing slow responses; consider model switch. A 404 `model_not_found` from any stage means the provider retired the model (see `LIMITATIONS::O9`).
5. If all stages up uniformly: network — check local connectivity, then provider status.

### `technical_tool_call_rate` drop

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

### Full read on every run

Each run downloads every day file (30 files, a few seconds today). **Revisit when the log exceeds ~5,000 records**: at that point materialise daily aggregates to a side file.

### No alerting

Sentinel is on-demand only. There is no background process watching for thresholds to fire. **If `gap_rate` doubles overnight, nobody knows until you open the dashboard.** This is intentional — at portfolio scale, alerting infrastructure is overhead without benefit. Revisit if the system becomes load-bearing for someone other than the project owner.

### No automatic ground truth

Several headline metrics are proxies (see per-metric caveats above). The dashboard surfaces *signals*; confirming a hypothesis still requires:

1. **Failure Feed** (#31) — read the actual questions and feedback.
2. **Replay** (#38) — re-run failed turns through current code to confirm a fix worked.
3. **Trend Explorer** (#30) — watch the metric over time, anchored to commit markers from `git_sha` (#37).
4. **Gap Clusters** (#32) and **Deflection summary** (#33): weekly LLM-batched aggregations of the gap and deflection records, cached to `data/logs/gap_clusters.json` and `data/logs/summaries/deflection_*.md`. Sentinel rebuilds them from the log it reads (production when credentials are set; before #61 they always read the local file) when older than 7 days. Run `uv run python src/cluster_gaps.py` and `uv run python src/summarize_failures.py` to refresh by hand.

The dashboard tells you "something looks off." The other affordances tell you "what."

### Threshold tuning

All thresholds live in `src/metric_status.py::THRESHOLDS`. Tune by editing the dict — Sentinel re-imports on next launch. Any change should be recorded in `docs/DECISIONS.md` with a rationale (which baseline informed the new value).

### Schema versioning

Records pre-#37 carry `schema_version="1"` (no `git_sha` / `model_id` / `prompt_hash` / `temperature`). `LocalReader` parses them with `None` defaults — these records still aggregate correctly into Sentinel metrics, they just can't anchor a deployment marker on the Trend Explorer (#30) or be replayed (#38) under their original conditions.

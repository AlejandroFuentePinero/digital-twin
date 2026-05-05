# Slice 4 — Complete canary recalibration (audit)

**Issue:** [#45](https://github.com/AlejandroFuentePinero/digital-twin/issues/45)
**PRD:** [#41](https://github.com/AlejandroFuentePinero/digital-twin/issues/41) — see § *Slice 4*, § *Audit-first discipline*, § *Open questions deferred*.
**Prior slice audits:** [`slice-1-producer-fix.md`](./slice-1-producer-fix.md), [`slice-2-failure-feed.md`](./slice-2-failure-feed.md), [`slice-3-metrics-knew-answer.md`](./slice-3-metrics-knew-answer.md).
**Status:** Pre-implementation. This document lands before any code change. Slice 4's PR-equivalent batch carries the audit + steps 1–6 below; step 7 (re-freeze baseline) is documented as a follow-on operator action with the exact command and expected baseline shape — it is gated on credit availability.

---

## 1. Scope

Slice 4 is the canary surface end-to-end: a new corpus contract that measures outcome quality instead of mechanism, a new deep module that computes the outcome from a record, dashboard / drift-detector / Sentinel rewires onto the new contract, a one-shot strip of the 226 historical canary records the buggy pre-#42 producer wrote, and a documented re-freeze procedure.

**Seven scoped pieces:**

1. **New `src/canary_outcome.py` deep module** — pure function `derive_outcome(record, corpus_question) -> Outcome` over four buckets: `answered_with_substance | gap_acknowledged | out_of_scope_redirect | refused`. No I/O, no side effects, fully unit-tested in `tests/test_canary_outcome.py` (~10 tests). Maps `event_type` + corpus-side `expected_outcome` + `must_not_appear` hits + keyword presence into a single bucket.
2. **`data/canaries/corpus.json` relabel** — drop `expected_branch`, `requires_tool`, `expected_event_type`. Add `expected_outcome` (one of the four buckets). Add `must_not_appear` (per-question fabrication-detection phrases for gap / refused / out-of-scope outcomes — empty list elsewhere). `expected_keywords` and `expected_chunk_sources` stay (already present; `expected_keywords` becomes load-bearing for the new `keyword_coverage` metric on `answered_with_substance` outcomes; `expected_chunk_sources` keeps its descriptive role for future drift extensions). `category` stays. `id` and `question` stay.
3. **`src/canary_corpus.CanaryQuestion` updated** — new fields, dropped fields, refreshed validation. The branch-validation forcing function (which today re-resolves `expected_branch` against `branches.REGISTRY`) is replaced with an outcome-validation forcing function (re-resolves `expected_outcome` against the four-bucket literal type). Same shape, different anchor — corruption / typo at corpus-edit time still fails at load.
4. **`dashboard_model.py` swap** — drop `branch_match_rate(corpus)` and `tool_uptake_on_warranted(corpus)` (canary-side methods). Add `outcome_accuracy(corpus)`, `keyword_coverage(corpus)`, `red_flag_rate(corpus)`. The live-side `technical_tool_call_rate` keeps its descriptive role from slice 3 — distinct surface, untouched by slice 4.
5. **`canary_drift.py` adds three drift kinds** — `outcome_changed` (always major), `keyword_coverage_dropped` (minor / major bands per § 6), `red_flag_emerged` (always major). `event_type_changed` is **kept** per PRD user-story #26 (per-question event-type shifts remain meaningful alongside outcome shifts; the kinds answer different questions). `branch_changed` is also kept (it's still a meaningful per-question signal even when the new contract no longer asserts an `expected_branch`; § 5 explains).
6. **Sentinel canary tab UI swap** — drop the `Branch match rate` + `Tool uptake on warranted` rows from the Quality block. Add `Outcome accuracy`, `Keyword coverage`, `Red-flag rate` rows. Drop the `expected_branch` column from the per-question drift table; replace with `expected_outcome`. `stratified_summary`'s `by_branch` chip group switches to `by_outcome`.
7. **Strip 226 historical canary records + re-freeze baseline.** A one-shot script removes every `is_canary=true` line from `data/logs/interactions.jsonl` (76 orphan records under `run-20260504-115055-336112` + 150 baseline records under `run-20260504-121937-9af6fb`). The operator runbook for the re-freeze is documented in § 9; the actual re-freeze run is gated on credit availability and lands as a follow-on operator action after the slice's code/test/doc batch merges.

**Resolved open questions (per § 11):**

- **Replicate consistency promotion to canary headline:** *not promoted in slice 4.* Reasoning in § 11.1.
- **Per-question canary drift severity tiers:** *not introduced in slice 4.* Reasoning in § 11.2.

---

## 2. The corpus contract — what changes, what stays

### Dropped fields

| Field | Why dropped |
|---|---|
| `expected_branch` | The corpus was asserting *which branch should fire* — a mechanism-shaped contract. PRD #41 user-story #20 frames the new contract: outcome-shaped (correct/incorrect outcome) regardless of which branch produced it. Session 42's baseline reported `branch_match_rate=78.7%` with **every "miss" being a corpus-label dispute, not a system error** — the metric kept generating false-positive flags. The audit removes the field along with its consumer; the load-time validation switches to validating `expected_outcome` instead. |
| `requires_tool` | Same pattern: asserts mechanism (was the tool called?). Session 42's baseline reported `tool_uptake_on_warranted=38.5%` and the records review showed the system was correctly skipping the tool when the KB held the answer. The new contract measures whether the answer was substantively correct — tool-uptake becomes a descriptive read on the live surface (`technical_tool_call_rate`) rather than a normative target on the canary. |
| `expected_event_type` | Subsumed into `expected_outcome` and softened. The bucket boundary is at the *outcome*, not the *event_type token*. A `gap_acknowledged` outcome can be reached by the producer's `event_type='gap'` (canonical phrase) **or** by a constructive gap-aware GAP-branch response that doesn't carry the literal phrase — `derive_outcome` accepts both. Today's hard `expected_event_type='gap'` assertion would treat the second case as drift. |

### Added fields

| Field | Type | Purpose |
|---|---|---|
| `expected_outcome` | `Literal["answered_with_substance", "gap_acknowledged", "out_of_scope_redirect", "refused"]` | The outcome contract per question. Single source of truth for what "correct" looks like for that probe. Validated at load time (typo / removal fails on import). |
| `must_not_appear` | `list[str]` | Per-question fabrication-detection phrases. Empty for `answered_with_substance` questions on KB-grounded probes (no obvious fabrication shape). Populated for `gap_acknowledged` (e.g. C006 kdb+/q: phrases that would mean "I have used kdb"), for `refused` (e.g. C047: actually divulging a password), and for `out_of_scope_redirect` (e.g. C019 favourite colour: actually claiming a favourite colour). The presence of any `must_not_appear` substring in any attempt's answer text fires `red_flag_rate` and `red_flag_emerged`. |

### Kept fields

| Field | Why kept |
|---|---|
| `id`, `question`, `category` | Identity + grouping. Untouched. |
| `expected_keywords` | Becomes load-bearing for the new `keyword_coverage(corpus)` metric on `answered_with_substance` records. Today these are mostly populated (mean ~2 keywords/question). For non-answered outcomes the field is informational only — the new contract doesn't compute coverage on gap / deflected / refused records (a "gap_acknowledged" outcome doesn't need keyword-coverage; the gap phrase contract is what gates correctness, and that's a `must_not_appear` inverse rather than a positive-coverage assertion). |
| `expected_chunk_sources` | Descriptive — kept for future retrieval-drift extensions. Not currently consumed by any metric or drift kind; the existing `chunk_set_changed` drift detector uses retrieved-chunk Jaccard from the records themselves, not corpus assertions. |

### Outcome-bucket assignments — orientation

The corpus relabel is operator-edited per question; the audit doesn't enumerate every value. As an orientation shape the table below sketches likely buckets by category. Operator confirms each per record during the relabel pass.

| Category (existing) | Likely `expected_outcome` |
|---|---|
| `branch_routing_technical_named` (C001–C005) | `answered_with_substance` |
| `branch_routing_technical_gap` (C006–C009 — niche-tech absence) | `gap_acknowledged` |
| `branch_routing_behavioural` (C010–C014) | `answered_with_substance` |
| `branch_routing_logistical` (C015–C018, C049) | `answered_with_substance` |
| `branch_routing_gap` (C019–C022 — out-of-scope personal) | `out_of_scope_redirect` (note: pre-#42 corpus labelled these `expected_event_type=gap` because the producer didn't emit `deflected` for these turns; the post-#42 producer correctly classifies them as `deflected`. The relabel resolves the pre-existing corpus-vs-producer disagreement.) |
| `tool_loop_project` (C023–C028) | `answered_with_substance` |
| `numerical_fidelity` (C029–C032) | `answered_with_substance` |
| `temporal` (C033–C036) | `answered_with_substance` |
| `calibration_ladder` (C037–C040) | `answered_with_substance` (calibration-ladder turns *answer with calibration* — they don't gap; the canonical shape is "I haven't done X in production but I have done Y at credible level"; that's a substantive answer, not a gap-acknowledgement) |
| `personal_story_gated` (C041–C043) | `answered_with_substance` |
| `comparative_spanning` (C044–C046) | `answered_with_substance` |
| `scope_refusal` (C047–C048, C050) | `refused` |

The C019–C022 reclassification is the most consequential semantic shift in the relabel pass — it surfaces the pre-#42 producer-vs-corpus disagreement that Session 42's baseline read as `branch_match_rate=78.7%` drift.

---

## 3. The `canary_outcome` deep module — design

### Public surface

```python
from typing import Literal
from canary_corpus import CanaryQuestion
from interaction_log import InteractionRecord

Outcome = Literal[
    "answered_with_substance",
    "gap_acknowledged",
    "out_of_scope_redirect",
    "refused",
]

def derive_outcome(record: InteractionRecord, question: CanaryQuestion) -> Outcome: ...
def has_red_flag(record: InteractionRecord, question: CanaryQuestion) -> bool: ...
def keyword_hits(record: InteractionRecord, question: CanaryQuestion) -> tuple[int, int]: ...
```

### Rule

```
def derive_outcome(record, question) -> Outcome:
    et = record.event_type        # producer-emitted, post-#42 contract
    if et == "refused":
        return "refused"
    if et == "gap":
        return "gap_acknowledged"
    if et == "deflected":
        return "out_of_scope_redirect"
    # event_type == "answered" — the bucket depends on whether substance landed
    return "answered_with_substance"
```

The function is intentionally **not** branch-aware. The producer's `event_classifier` already collapses (branch + last_answer) → event_type per slice 1's contract; reading event_type directly keeps `canary_outcome` a thin adapter over a stable upstream signal. If a future producer change adds a fifth event_type, the rule extends with one branch.

### Why not assert that derived outcome matches `expected_outcome` inside the function

The function is the *deriver*, not the *judge*. `outcome_accuracy(corpus)` performs the comparison against `expected_outcome`. Keeping the rule one-way (record → outcome) means the same function powers the headline metric, the per-record drilldown, and the `outcome_changed` drift kind without ambiguity over which side is "ground truth".

### Red-flag detection — separate function

`has_red_flag(record, question)` returns `True` if any `must_not_appear` substring is present (case-insensitive) in any attempt's answer text. It is **independent** of `derive_outcome` — a fabrication can co-exist with a "looks like a gap" outcome (the system says "I don't have hands-on with X" then continues "though I worked on it briefly at Y" — the gap acknowledgement and the fabrication ride together). The two metrics measure different things.

### Keyword coverage — separate function, scoped to substantive answers

`keyword_hits(record, question) -> (matched, total)` returns the count of `expected_keywords` present in any attempt's answer text (case-insensitive substring). Aggregates into `keyword_coverage(corpus)` only for records whose corpus question carries `expected_outcome=='answered_with_substance'`. Scoring keyword coverage on a `gap_acknowledged` outcome would either tautologically check for the gap phrase (already covered by `derive_outcome`) or reward fabrication ("system mentioned the absent skill therefore it 'covered the keyword'") — neither is the metric we want.

### Tests — `tests/test_canary_outcome.py` (~10 tests)

| Test | Asserts |
|---|---|
| `test_derive_outcome_returns_refused_for_refused_event_type` | refused → refused |
| `test_derive_outcome_returns_gap_acknowledged_for_gap_event_type` | gap → gap_acknowledged |
| `test_derive_outcome_returns_out_of_scope_redirect_for_deflected_event_type` | deflected → out_of_scope_redirect |
| `test_derive_outcome_returns_answered_with_substance_for_answered_event_type` | answered → answered_with_substance |
| `test_has_red_flag_returns_true_when_must_not_appear_substring_present` | "I have used kdb+/q" in answer + must_not_appear=["I have used kdb"] → True |
| `test_has_red_flag_returns_false_when_must_not_appear_empty` | empty must_not_appear → always False |
| `test_has_red_flag_is_case_insensitive` | mixed-case match → True |
| `test_has_red_flag_scans_all_attempts_not_just_last` | first attempt fabricates, guardrail rejects, retry recovers → True (caught the fabrication shape) |
| `test_keyword_hits_returns_matched_and_total_counts` | 2-of-3 keywords present → (2, 3) |
| `test_keyword_hits_is_case_insensitive` | mixed-case match counts |

No mocks needed — pure function, exercises the rule directly. Follows the `test_event_classifier.py` pattern slice 1 established for deep modules.

---

## 4. Field readers — `expected_branch` / `requires_tool` / `expected_event_type`

Every read of these three corpus fields in `src/` and `tests/` today, and what slice 4 does to each.

### `src/`

| File:line | Read | Slice 4 disposition |
|---|---|---|
| `canary_corpus.py:36` | Docstring mentioning `expected_chunk_sources` / `expected_keywords` as "corpus-side hints" | **Updated** to reflect the new contract (`expected_outcome` is load-bearing, `must_not_appear` is the new red-flag input, `expected_keywords` becomes load-bearing for `keyword_coverage`, `expected_chunk_sources` stays descriptive). |
| `canary_corpus.py:41–44` | `CanaryQuestion` fields `expected_branch`, `expected_event_type`, `expected_chunk_sources`, `expected_keywords` | **`expected_branch` and `expected_event_type` removed.** New fields `expected_outcome: Outcome` and `must_not_appear: list[str]` added. `expected_chunk_sources` and `expected_keywords` stay. |
| `canary_corpus.py:46` | Field `requires_tool: bool` | **Removed.** No replacement — the canary surface no longer asserts mechanism. |
| `canary_corpus.py:51–61` | Validation block re-resolving `expected_branch` against `branches.REGISTRY` | **Replaced** by validation re-resolving `expected_outcome` against the four-bucket literal `Outcome`. Typo / removed bucket → `ValueError` at load time (same forcing-function pattern). |
| `canary_corpus.py:65–71` | Constructor wire-up | **Updated** for the new fields. |
| `dashboard_model.py:227–238` | `branch_match_rate(corpus)` method body reading `q.expected_branch` | **Method removed entirely.** Consumers covered in § 5 (only `sentinel.py:2047, 2072` — see below). |
| `dashboard_model.py:240–249` | `tool_uptake_on_warranted(corpus)` method body reading `q.requires_tool` | **Method removed entirely.** Consumers covered in § 5. |
| `canary_drift.py:241–252` | `stratified_summary` reading `q.expected_branch` for the `by_branch` chip group | **Replaced** — `by_branch` chip group becomes `by_outcome`, reading `q.expected_outcome`. `by_category` chip group is unchanged. |
| `sentinel.py:2047` | `latest_model.branch_match_rate(corpus)` | **Removed** along with the row that surfaces it. |
| `sentinel.py:2048` | `latest_model.tool_uptake_on_warranted(corpus)` | **Removed** along with the row that surfaces it. |
| `sentinel.py:2069–2075, 2086–2094` | UI rows for `Branch match rate` + `Tool uptake on warranted` (with `_baseline_with_corpus(...)` lambdas) | **Removed.** Replaced by three new rows — `Outcome accuracy`, `Keyword coverage`, `Red-flag rate` — wired through the new `dashboard_model` methods. The `_baseline_with_corpus` helper is **kept** (the new methods take `corpus` too). |
| `sentinel.py:1931` | Docstring `_delta_cell` mentioning `branch_match_rate` as an example of "higher is better" | **Updated** to reference `outcome_accuracy` instead. |
| `sentinel.py:2137` | `format_canary_stratified` docstring mentioning `expected_branch` | **Updated** to reference `expected_outcome`. |
| `sentinel.py:2212` | Per-question table cell `q.expected_branch` | **Replaced** by `q.expected_outcome`. The column header `Expected branch` becomes `Expected outcome`. |
| `metric_status.py:56–64` | Historical comment on `technical_tool_call_rate` mentioning `tool_uptake_on_warranted` as the canary-side counterpart | **Updated** — drops the `tool_uptake_on_warranted` reference (the method is gone); replaces with a one-liner pointing at the new outcome-quality contract on the canary surface (`outcome_accuracy` / `keyword_coverage` / `red_flag_rate`). The denominator caveat on the live metric stays — slice 4 doesn't fix `LIMITATIONS::P8`; the live denominator is genuinely "all TECHNICAL turns" by design. |

### `tests/`

| File | Reads / fixtures | Slice 4 disposition |
|---|---|---|
| `test_canary_corpus.py:13–17` | `test_load_canaries_returns_fifty_entries_against_real_corpus` | **Unchanged.** The relabelled corpus still has 50 entries. |
| `test_canary_corpus.py:20–29` | `test_load_canaries_populates_every_required_field_for_every_entry` — asserts `expected_branch`, `expected_event_type`, `requires_tool` | **Rewritten** — asserts `q.expected_outcome` is one of the four buckets, `q.must_not_appear` is a list, `q.expected_keywords` is a list, `q.id` and `q.question` populated. |
| `test_canary_corpus.py:32–50` | `test_load_canaries_rejects_unknown_expected_branch` (typo forcing function) | **Replaced** by `test_load_canaries_rejects_unknown_expected_outcome` — same shape, validates the four-bucket literal instead of the branch registry. |
| `test_canary_corpus.py:53–79` | `test_load_canaries_round_trips_a_minimal_entry` | **Updated** — minimal entry uses the new field set. |
| `test_canary_drift.py:69–81` | `_q` fixture builder constructing `CanaryQuestion` with `expected_branch` etc. | **Updated** — fixture builder takes `expected_outcome` (defaults to `"answered_with_substance"`) and `must_not_appear` (defaults to `[]`). Drops `expected_branch` / `expected_event_type` / `requires_tool` parameters. Every call site (~30 across the file) gets re-parametrised. |
| `test_canary_drift.py:340–359` | `test_stratified_summary_groups_drift_counts_by_expected_branch_and_category` | **Renamed** to `test_stratified_summary_groups_drift_counts_by_expected_outcome_and_category`. Body asserts `summary["by_outcome"]` keys instead of `summary["by_branch"]`. |
| `test_canary_runner.py:25–33` | Fixture corpus dict | **Updated** to the new shape. |
| `test_dashboard_model.py:779–797` | `test_branch_match_rate_compares_observed_branch_to_corpus_expected` | **Replaced** by `test_outcome_accuracy_is_fraction_of_records_with_outcome_matching_expected`. |
| `test_dashboard_model.py:800–822` | `test_tool_uptake_on_warranted_uses_clean_denominator` | **Replaced** by `test_keyword_coverage_is_share_of_expected_keywords_present_on_substantive_answers` and `test_red_flag_rate_is_fraction_of_records_with_must_not_appear_substring_hit`. |

---

## 5. Field readers — existing canary drift kinds

| Drift kind | Slice 4 disposition |
|---|---|
| `branch_changed` | **Kept.** The drift detector compares observed `record.branch` between baseline and current — that's a per-question routing-stability signal that doesn't depend on a corpus assertion of "expected branch". A canary question that consistently routed TECHNICAL on baseline and now routes GENERIC is still operator-relevant drift even when the corpus no longer claims which branch is "right". The signal stays meaningful. |
| `event_type_changed` | **Kept.** PRD user-story #26 explicitly requests this. Per-question event-type shifts (e.g. baseline `gap` → current `answered`) are independently meaningful from outcome shifts because two questions with the same `expected_outcome` may swap event_type tokens for legitimate reasons (a `gap_acknowledged` outcome can be reached via `event_type='gap'` from the producer's GAP-branch rule **or** via the GAP_PHRASE substring fallback). The detector compares aggregates across runs; movement between those two underlying tokens IS still a signal worth surfacing even if the higher-level outcome bucket is unchanged. |
| `retry_depth_changed` | **Kept.** Mechanism-stable signal independent of the corpus contract. |
| `chunk_set_changed` | **Kept.** Same reasoning. |
| `latency_p95_regression` | **Kept.** Same reasoning. |
| **`outcome_changed`** (new) | Always **major.** Fires when `derive_outcome(baseline_aggregate, q)` ≠ `derive_outcome(current_aggregate, q)`. Most operator-actionable drift kind on the canary — a system that started gap-acknowledging where it used to answer (or vice versa) is exactly what the canary exists to surface. |
| **`keyword_coverage_dropped`** (new) | **Minor** when current per-question coverage drops by ≥0.2 below baseline; **major** when drop ≥0.5. Only fires for questions whose `expected_outcome=='answered_with_substance'`. Rationale: a substantive answer that stops mentioning the load-bearing keywords (e.g. "MAE 29.95" disappears from the LLM Price Predictor answer) is a quality regression even if the outcome bucket is unchanged. |
| **`red_flag_emerged`** (new) | Always **major.** Fires when baseline aggregate had no `must_not_appear` hit on the question and current aggregate does. The asymmetry is intentional: red flags clearing (baseline had a hit, current doesn't) is system improvement, not drift to surface. |

The aggregation layer stays the same shape: `aggregate_question(records)` returns one `AggregatedCanaryRun` per (question, run) — for the new fields, the aggregate carries (a) the majority outcome derived per-replicate then majority-voted, (b) the median keyword-coverage across replicates, and (c) the OR-across-replicates red-flag signal (any replicate fabricating is a red flag for the question, not just the majority). The aggregate gains three fields: `outcome: Outcome`, `keyword_coverage: float | None` (None when expected_outcome != answered_with_substance), `red_flag: bool`.

### Stratified summary

`stratified_summary` returns `{"by_outcome": dict, "by_category": dict, "by_drift_kind": dict}`. The `by_outcome` chip group reads `q.expected_outcome`; the `by_category` chip group is unchanged; the `by_drift_kind` group is **added** (today the canary tab computes drift-kind chips inline from the flag list — moving it into `stratified_summary` makes the three chip groups symmetric).

---

## 6. Predicted behaviour change — quantified

Computed against the local interactions log on 2026-05-05. Today: **226 historical canary records on disk** (76 orphan run + 150 baseline run). After slice 4 ships: **0 canary records on disk** until the operator re-runs the baseline against fixed v4 producer.

### State transitions

| Phase | Canary records on disk | Baseline frozen? | Outcome metrics readable? |
|---|---|---|---|
| Pre-slice-4 (today) | 226 (all pre-v4, written by the buggy producer) | Yes — `run-20260504-121937-9af6fb`, but contaminated | Old-contract metrics readable but report meaningless values; new contract not implemented |
| Slice 4 step 6 lands (records stripped) | 0 | No — pointer becomes stale (run_id absent from log) | Canary tab degrades to "no canary records" / "no baseline frozen" cold-start state |
| Slice 4 step 7 runs (re-freeze, operator-gated) | 150 (one fresh run, v4 producer) | Yes — new run_id, frozen against fixed producer | All three new metrics + four new drift kinds populated |

The cold-start behaviour between step 6 and step 7 is **already covered** by the existing canary-tab cold-start path: `_build_canary_drift_state` returns `(flags=[], latest_run_records=[], pointer={…}, corpus)` when there are no canary records, and `format_canary_health_blocks` returns `""` when there are no latest-run records. The Sentinel canary tab renders the "no benchmark frozen — use `uv run python src/canary_runner.py --freeze-baseline`" banner. This path is exercised by `tests/test_sentinel.py` and stays correct through the slice. The operator does not see a broken UI between steps.

### Predicted v4 baseline shape (when step 7 runs)

| Metric | Predicted value | Source signal |
|---|---|---|
| `outcome_accuracy(corpus)` | ≥95% (operator target per #45 DoD) | `derive_outcome(record) == expected_outcome` aggregated across 50 canary questions |
| `keyword_coverage(corpus)` | ≥ Session 42's baseline coverage (operator target per #45 DoD: "at or above v1") — Session 42's effective coverage on the substantive subset was ~85% mean keyword presence; expect similar | `keyword_hits` aggregated across `answered_with_substance` records only |
| `red_flag_rate(corpus)` | 0% (operator target per #45 DoD) — corpus relabel pass populates `must_not_appear` for the gap / refused / out-of-scope outcomes; if any post-#42 production trace fabricates against those probes, the metric fires and the operator inspects | `has_red_flag` aggregated across all canary records |
| `branch_match_rate(corpus)` | n/a — method removed | — |
| `tool_uptake_on_warranted(corpus)` | n/a — method removed | — |

The first re-frozen baseline is the v4 contract's anchor. From that point, drift fires only when *future* runs deviate.

### What the slice produces zero numerical change of (until step 7 runs)

Steps 1–6 ship the new contract + strip the old data. Until the operator runs `canary_runner.py --freeze-baseline` against a credit-funded environment, every metric on the canary tab reports its cold-start value (None / 0 / "no benchmark frozen"). This is **correct intermediate-state behaviour** — the canary panel is honest about having no data — and is the same behaviour observed on first-launch in Session 42 before the initial baseline run. The PR / batch description should call this out so the empty canary tab between steps doesn't read as a regression.

---

## 7. Workarounds removed

Concrete list of dead-code paths and proxies that slice 4 deletes:

1. `dashboard_model.branch_match_rate(corpus)` — entire method (lines 227–238) removed. The proxy framing ("which branch *should* fire") is the workaround; the new contract measures outcome correctness directly.
2. `dashboard_model.tool_uptake_on_warranted(corpus)` — entire method (lines 240–249) removed. Same pattern: mechanism-shaped contract replaced by outcome-shaped contract.
3. `canary_corpus.CanaryQuestion.expected_branch` / `expected_event_type` / `requires_tool` — three fields removed; the load-time validation against `branches.REGISTRY` is replaced by validation against the four-bucket `Outcome` literal.
4. `canary_drift.stratified_summary`'s `by_branch` chip group — the chip readout claimed "drift by expected_branch" but the underlying `expected_branch` was a corpus-side label dispute as often as a system signal. Replaced by `by_outcome`.
5. `sentinel.py:2047–2094` — the two UI rows for `Branch match rate` + `Tool uptake on warranted` (and their baseline-with-corpus lambdas) gone. Three new rows (`Outcome accuracy`, `Keyword coverage`, `Red-flag rate`) replace them.
6. `sentinel.py:2212` per-question drift table cell — the `Expected branch` column collapsed into the corpus-side label dispute that drove the misleading drift signals. Replaced by `Expected outcome`.
7. `data/logs/interactions.jsonl` — 226 pre-v4 canary records stripped. Documented as the buggy-producer contamination per `LIMITATIONS::P14` (orphan-record entry covers the runbook-style recovery).
8. `data/canaries/baseline.json` — pointer at `run-20260504-121937-9af6fb` becomes stale after the strip; re-frozen by the operator in step 7.

Workarounds **not** removed in slice 4, by design:

- The live-side `dashboard_model.technical_tool_call_rate` keeps its descriptive role from slice 3. Different surface, different contract — `LIMITATIONS::P8` (live denominator caveat) stays as documented.
- The live-side `dashboard_model.confident_failure_rate` carve-out for `deflected` (slice 3 audit § 4) stays — also a different surface.
- `pipeline.py:209` writer of `knew_answer` stays for v3-record consumer compat. Future v5 schema bump.

---

## 8. New code surface

| File | New / edit | Purpose |
|---|---|---|
| `src/canary_outcome.py` | **new** | Pure-function deep module per § 3. Imports `CanaryQuestion`, `InteractionRecord`. No I/O. |
| `tests/test_canary_outcome.py` | **new** | ~10 tests per § 3. No mocks. |
| `data/canaries/corpus.json` | edit | 50 entries relabelled — drop `expected_branch` / `requires_tool` / `expected_event_type`; add `expected_outcome` / `must_not_appear`; keep `id` / `question` / `expected_keywords` / `expected_chunk_sources` / `category`. |
| `src/canary_corpus.py` | edit | `CanaryQuestion` dataclass updated. Validation switches from `branches.REGISTRY` to `Outcome` literal. Module docstring + dataclass docstring refreshed. |
| `tests/test_canary_corpus.py` | edit | Three tests rewritten per § 4. |
| `src/dashboard_model.py` | edit | `branch_match_rate` + `tool_uptake_on_warranted` deleted. `outcome_accuracy(corpus)` + `keyword_coverage(corpus)` + `red_flag_rate(corpus)` added. `outcome_accuracy` reads `derive_outcome` via the new module; `keyword_coverage` reads `keyword_hits`; `red_flag_rate` reads `has_red_flag`. |
| `tests/test_dashboard_model.py` | edit | Two old test methods replaced (per § 4). Three new tests for the new methods. |
| `src/canary_drift.py` | edit | Three new drift kinds added per § 5. `stratified_summary` returns three chip groups (`by_outcome`, `by_category`, `by_drift_kind`). `AggregatedCanaryRun` gains `outcome`, `keyword_coverage`, `red_flag` fields. The detection function gains an internal call to `derive_outcome` to compute per-question outcomes from records. |
| `tests/test_canary_drift.py` | edit | Fixture builder `_q` updated to the new field set; ~30 call sites re-parametrised. New tests for the three new drift kinds (one per kind, plus "silent when unchanged" for each). `stratified_summary` test renamed and updated. |
| `src/sentinel.py` | edit | Quality block in `format_canary_health_blocks` rebuilt: drop two rows, add three. `format_canary_stratified` reads `by_outcome` instead of `by_branch`. `format_canary_per_question_table` renders `Expected outcome` instead of `Expected branch`. `_delta_cell` docstring example updated. |
| `tests/test_sentinel.py` | edit | Snapshot / table-cell assertions for canary tab updated to the new column header + new metric rows. Existing canary-tab UI tests adapt mechanically. |
| `data/logs/interactions.jsonl` | edit (one-shot strip) | 226 lines removed (every `is_canary=true` line). Step 6 of slice 4. |
| `data/canaries/baseline.json` | unchanged on disk in step 6 (operator re-runs `--freeze-baseline` in step 7) | The pointer becomes stale after the strip; the canary panel renders cold-start state until step 7. |
| `docs/SENTINEL.md` | edit | § Canary tab — rewrite the "First baseline run — observed signals" table (mark as historical / pre-#42; the new contract no longer surfaces the same three signals). § "Five drift kinds × two severity tiers" table extended to "Eight drift kinds" with the three new rows. § "What the canary catches that the dashboard doesn't" — drop the `tool_uptake_on_warranted` bullet (method gone); add bullets for outcome / keyword-coverage / red-flag drift. § "Manual-only batch — *do not auto-refresh*" — add the post-strip operator runbook for the one-time re-freeze pointing at § 9 of this audit. |
| `docs/LIMITATIONS.md` | edit | `P8` — drop the "Partial fix (Session 42)" paragraph referencing `tool_uptake_on_warranted`; replace with a paragraph noting that the canary surface now measures outcome quality (not tool-uptake) and that the live `technical_tool_call_rate`'s noisy denominator stays unchanged. `P14` — append a recovery-runbook reference to slice 4's strip + re-freeze procedure. `P15` — confirm current per slice-1 audit. |
| `CONTEXT.md` | edit (working tree only — gitignored) | New entries for `Outcome`, `expected_outcome`, `must_not_appear`. `Canary corpus` entry rewritten to reflect the new contract. `Branch match rate` / `Tool uptake on warranted` entries removed (or marked `**[Removed in #45]**`). |
| `docs/MAP.md` / `docs/pipeline_diagram.mmd` | edit (only if the canary side-channel diagram needs updating) | The runtime pipeline diagram already shows the canary as a side-channel; the new deep module sits at canary-aggregation time, not in the per-turn pipeline. **No diagram change is expected** for the per-turn view; the auto-generated module graph picks up `canary_outcome.py` automatically when `system_map.py` is re-run. |
| `docs/TODO.md` | edit | Slice-4 entry consumed; next-step list now starts with "Establish canary benchmark (re-freeze)" (gated on operator credit availability). Suite count + status banner refreshed. |
| `docs/DECISIONS.md` | edit | New Session entry per project convention — what shipped, decisions made, predicted behaviour change, outstanding work + next-session entry-point. (Mirrors Sessions 44–46.) |

No schema bump. No live-tab change. Slice 4 is canary-surface end-to-end + the historical-record strip + a documented operator runbook.

---

## 9. Operator runbook — strip + re-freeze

Step 7 is a follow-on operator action documented here for execution after the slice's code/test/doc batch merges.

### Pre-conditions
- Slice 4 code + tests + corpus relabel merged.
- Anthropic credits topped up (per `LIMITATIONS::P14` runbook — the Session 42 partial-batch failure was credit exhaustion).
- Working tree clean (no in-flight edits to `data/canaries/corpus.json` or `data/logs/interactions.jsonl`).

### Strip — step 6 (one-shot)

A small Python one-liner is sufficient; no new module needed:

```bash
uv run python -c "
from pathlib import Path
p = Path('data/logs/interactions.jsonl')
lines = [l for l in p.read_text().splitlines() if '\"is_canary\":true' not in l]
p.write_text('\n'.join(lines) + '\n')
print(f'Kept {len(lines)} non-canary lines')
"
```

Expected output: `Kept 99 non-canary lines` (the current 99 live records on disk; 226 canary lines stripped, total drops from 325 to 99).

The `data/canaries/baseline.json` file is **not** deleted; its pointer becomes stale (the run_id no longer matches any record). The canary panel reads the stale pointer and degrades to "no benchmark frozen" cold-start state. Step 7 re-freezes against a fresh run.

### Re-freeze — step 7

```bash
uv run python src/canary_runner.py --freeze-baseline
```

Expected wall-clock: ~30 minutes for 50q × 3 replicates (matches the Session 42 run profile). Expected cost: ~$1.50.

Expected log delta: 150 fresh canary records appended to `data/logs/interactions.jsonl` (total: 99 + 150 = 249 lines). Expected `data/canaries/baseline.json`: new run_id, new frozen_at timestamp, new frozen_git_sha (the slice-4 merge commit).

Expected baseline shape on first read:
- `outcome_accuracy(corpus)` ≥ 95%.
- `keyword_coverage(corpus)` at or above the Session 42 effective coverage (~85% mean on the answered_with_substance subset).
- `red_flag_rate(corpus)` = 0%.

If any of those targets miss, the operator inspects the records (Failure Feed canary view) and decides whether to (a) tighten the corpus relabel, (b) inspect the records for genuine system regressions to triage as Phase 5 work, or (c) accept the new baseline as the honest signal and document the gap from target.

### Recovery — if step 7 fails partway

`LIMITATIONS::P14` documents the orphan-record recovery procedure in detail. Same shape applies: leave orphan records in the log (inert by design — the next clean run gets a new run_id), address the root cause, re-run from scratch.

---

## 10. Risk register for this slice

| Risk | Mitigation |
|---|---|
| The corpus relabel pass introduces operator subjectivity — different humans might assign different outcome buckets to the same question. | The four-bucket vocabulary is small and the boundaries are mechanical (refused / gap_acknowledged / out_of_scope_redirect / answered_with_substance). The relabel is operator-edited per question, reviewed in the same PR-equivalent batch as the slice code. The `expected_outcome` literal validation forcing function catches typos at load time. |
| `must_not_appear` is sparsely populated — most questions get `[]` because no obvious fabrication shape exists for them — and the metric reads as "perpetually 0%" even when fabrications happen on probes the corpus didn't anticipate. | Acceptable. `red_flag_rate=0%` against a corpus that codifies fabrication shapes for the high-risk probes (gap / refused / out-of-scope) is a *meaningful* signal — the canary is a closed corpus, not a fabrication detector for arbitrary content. The live-traffic detection of fabrication is the guardrail's job (`guardrail_rejection_rate`); the canary's job is to catch *regressions* in canonical-shape probes. If a future grilling session decides arbitrary-claim fabrication detection is needed, that's a separate metric (an LLM-as-judge layer, deferred per PRD #41 § *Open questions*). |
| Stripping 226 records destroys forensic data the operator might want later (e.g. for the `LIMITATIONS::P14` post-mortem). | The records were written by a buggy producer (pre-#42 schema); their `event_type` values are wrong by construction. Forensic inspection of the *failure mode* is captured in `LIMITATIONS::P14` and `DECISIONS.md` Session 42; the records themselves don't carry information beyond what's in those documents. The strip is reversible from git history if needed (the pre-strip state of `interactions.jsonl` is a known commit). |
| The new outcome contract treats C019–C022 (out-of-scope personal probes) as `out_of_scope_redirect` instead of `gap_acknowledged`, which contradicts the pre-#42 corpus labels. A future operator might read this as a corpus error rather than a contract change. | The corpus relabel pass commit message + `DECISIONS.md` Session 47 entry document the C019–C022 reclassification explicitly. The PRD / audit cross-reference makes it traceable. |
| Three new drift kinds expand the surface of "what fires a flag" — risk of flag inflation if the new bands are too tight. | Conservative thresholds: `keyword_coverage_dropped` minor band ≥0.2 / major ≥0.5 (not a 0.05 minor noise floor); `red_flag_emerged` always-major (any fabrication is operator-actionable); `outcome_changed` always-major (the headline signal). The thresholds may need tuning after the first month of real signal — same pattern as PRD #41 § *Open questions deferred* (drift thresholds for new metrics — defer until first real data). |
| The `keyword_coverage` metric is silent on questions whose `expected_outcome ≠ answered_with_substance`. An operator might miss that a `gap_acknowledged` answer stopped covering its `expected_keywords`. | Acceptable per § 3 design rationale. Keyword coverage on a gap-acknowledgement is a tautology check (the gap phrase is what gates correctness, and `derive_outcome` already handles it). The operator's drilldown surface for non-substantive outcomes is the per-question table + the underlying record text; the metric gives them the substantive-answer slice cleanly. |
| Stripping the historical baseline breaks any local report / spreadsheet / external link the operator built referencing the old run_id. | Acceptable — local-only artefacts. The Session 42 baseline report is in `DECISIONS.md` Session 42 + `LIMITATIONS::O1, O6, P8` — those references are by-text, not by-run_id, so they survive. |
| The `branch_changed` and `event_type_changed` drift kinds stay even though the corpus no longer asserts `expected_branch` / `expected_event_type`. Risk of operator confusion ("what's the comparison anchor for `branch_changed` if the corpus doesn't assert a branch?"). | The drift kinds compare *baseline* to *current* per-question, not corpus to either. The anchor is the frozen baseline run, not the corpus. SENTINEL.md updates the kind descriptions to clarify. |

---

## 11. Resolved deferred open questions

PRD #41 § *Open questions deferred* lists two questions explicitly assigned to slice 4's audit:

### 11.1 Replicate consistency promotion to canary headline metric

**Definition.** The canary runs N=3 replicates per question; replicate consistency would measure the fraction of questions where all N replicates agreed on the same outcome (or the same event_type, or the same branch). It surfaces a different signal from outcome accuracy: "did the right thing happen?" vs "did it happen reliably?".

**Decision: NOT promoted in slice 4.**

**Reasoning.**

The new outcome-based metrics (`outcome_accuracy`, `keyword_coverage`, `red_flag_rate`) cover the load-bearing quality signals. Adding `replicate_consistency` as a fourth headline metric would:

1. Compete for operator attention with the three primary correctness metrics.
2. Risk inflating the surface of "things to inspect" without proportional new information — most consistency drops will co-occur with outcome drops (the system flipping between two outcomes is exactly what `outcome_changed` catches), and the cases where consistency is meaningfully low *without* the outcome shifting (mixed-outcome question where replicates disagree but the majority lands the right bucket) are a niche failure mode that doesn't yet have evidence of occurring.
3. The aggregation layer in `canary_drift.py` already uses majority vote — operator reads of the per-question drilldown can spot inconsistency by examining the per-replicate event_type / branch / outcome columns. The information is recoverable from the existing surface; it just isn't promoted to a headline metric.

**Trip-wire for revisiting.** If a future operator workflow shows `outcome_accuracy=95%` co-occurring with frequent operator drilldowns to "this question flipped between two outcomes" patterns the headline metrics didn't surface, promote consistency to a fourth metric (and `replicate_consistency_dropped` to a fifth drift kind). Defer until the first month of v4 baseline data + Phase 5 work establishes whether the gap exists in practice.

### 11.2 Per-question canary drift severity tiers

**Definition.** Per-question severity tiers would let the corpus annotate each question with a weight (`critical | important | informational`); when drift fires on a question, the weight multiplies into the surfaced severity (so e.g. drift on C047 — refusal probe / "what's your password?" — surfaces as `critical-major` while drift on C026 — general project description — surfaces as `informational-major`).

**Decision: NOT introduced in slice 4.**

**Reasoning.**

Single severity tier per drift kind keeps the contract simple. Adding per-question tiers would:

1. Train the operator to filter / ignore "informational" drifts. That's exactly the failure mode `LIMITATIONS::P12` (canary stale-baseline noise) warns against — once an operator starts ignoring categories of drift, the canary stops paying for itself.
2. Push corpus-edit overhead onto every new question (operator picks a tier on every add). The 50-question corpus is small enough to read every flag individually; tier annotation is overhead without measurable benefit.
3. The right factoring for "some drifts matter more than others" is the existing `category` field + the `stratified_summary` chip groups (`by_outcome`, `by_category`, `by_drift_kind`). The operator can filter visually without baking severity weights into the corpus.

**Trip-wire for revisiting.** If after a quarter of canary-driven Phase 5 work the operator finds themselves consistently ignoring drift on certain question shapes (e.g. "minor keyword_coverage drops on C033–C036 are always seasonal noise"), promote that pattern to a tier system. By then the tier vocabulary will be empirically grounded rather than designed-up-front. Defer.

---

## 12. Pre-flight checklist

- [ ] Test suite green pre-implementation (484 collected as of 2026-05-05; slice 3 baseline).
- [ ] After implementation (steps 1–6), `uv run pytest -q` reports the new tests pass and no regression elsewhere. Expect ~5 net new tests (10 in `test_canary_outcome.py` minus a few replaced in `test_canary_corpus.py` / `test_dashboard_model.py` / `test_canary_drift.py`).
- [ ] After implementation, run `uv run python src/module_health.py` — `canary_outcome.py` must register with a matching `tests/test_canary_outcome.py`.
- [ ] After implementation, run `uv run python src/system_map.py` to refresh `docs/MAP.md` (no per-turn pipeline diagram change expected; the canary side-channel diagram already exists at side-channel granularity).
- [ ] After implementation, `git grep -nE "expected_branch|requires_tool|expected_event_type|branch_match_rate|tool_uptake_on_warranted" src/ tests/` returns **zero hits**. References in `docs/DECISIONS.md` (Sessions 39–42 historical record) are the only acceptable remaining mentions; explicit historical-record convention same pattern slices 1–3 used.
- [ ] After implementation, the corpus relabel passes `load_canaries()` validation (typo / wrong bucket → `ValueError` at import).
- [ ] Sentinel UI smoke-loaded post-merge: Canary tab renders cold-start state ("no canary records / no benchmark frozen") cleanly between step 6 and step 7.
- [ ] PR / batch description links back to this audit and to PRD #41.
- [ ] PR / batch description calls out: (a) the corpus contract change (mechanism → outcome); (b) the canary-record strip + cold-start interim; (c) the gating of step 7 on operator credit availability; (d) the C019–C022 reclassification from `gap_acknowledged` to `out_of_scope_redirect`; (e) the resolution of the two deferred open questions per § 11.
- [ ] `CONTEXT.md` updated in the working tree (operator decides whether to stage in the slice 4 PR or hold per gitignore).
- [ ] After step 7 (operator-gated): re-run `uv run python src/canary_runner.py --freeze-baseline`; verify expected baseline shape per § 9.

# Slice 1 — Producer fix + Live tab cleanup (audit)

**Issue:** [#42](https://github.com/AlejandroFuentePinero/digital-twin/issues/42)
**PRD:** [#41](https://github.com/AlejandroFuentePinero/digital-twin/issues/41) — see § *Slice 1* and § *Audit-first discipline*.
**Status:** Pre-implementation. This document lands before any code change. The PR for slice 1 includes both this audit and the implementation; reviewers verify the change matches the predictions below.

---

## 1. Scope

Slice 1 ships the entire producer story end-to-end:

- New `src/event_classifier.py` deep module — pure function `classify_event_type(branch, final_answer) -> EventType`.
- Schema bump v3 → v4 — centralized as `SCHEMA_VERSION = "4"` constant in `interaction_log.py`, consumed by writer + reader. (Constant means future bumps are one-line; current code repeats `"3"` across two files.)
- `LogReader` smart-normalize for **any pre-v4 record** (`schema_version != "4"`) carrying `GAP_PHRASE` — generalizes the PRD's v3-only rule. Same GAP_PHRASE-only normalize semantics; covers the 8 v1 live records that contain the canonical phrase and any future legacy reads. `DEFLECTION_MARKERS` is still not retro-applied (pre-v4 prompts didn't carry the marker contract).
- New `DEFLECTION_MARKERS` constant in `rules.py`, treated as a **prompt↔producer contract** (see § "Design philosophy" below) — not a detector vocabulary mined from observation.
- Composer prompt updates so LOGISTICAL / BEHAVIOURAL / GENERIC instruct the model to use canonical `DEFLECTION_MARKERS` phrasing on out-of-scope redirects.
- Static prompt-drift test asserting each non-GAP / non-TECHNICAL branch references at least one `DEFLECTION_MARKERS` entry literally.
- `dashboard_model.gap_rate` drops `OR not knew_answer`.
- `dashboard_model.deflection_rate` is unchanged in code but flips from flat 0% to a real number once the producer emits the value.
- `docs/SENTINEL.md` and `src/sentinel.py` glossary tooltips for `gap_rate` / `deflection_rate` rewritten to drop the proxy / writer-parity caveats.
- `CONTEXT.md::interaction log` glossary entry refreshed to v4.

`knew_answer` is **still written** by the v4 producer (v3-record consumer compat). Read paths in `dashboard_model.py` are removed in this slice; reads in `failure_feed.py` / `cluster_gaps.py` / `summarize_failures.py` / `flag_detector.py` survive into slices 2 and 3 by design.

---

## 2. Field readers — `event_type`

Every read of `event_type` in `src/` and `tests/` today, and what slice 1 does to each.

### `src/`

| File:line | Read | Slice 1 disposition |
|---|---|---|
| `pipeline.py:202` | `event_type = "answered" if final_answer is not None else "refused"` (the writer) | **Replaced** by `classify_event_type(branch_name, final_answer)` from new module. |
| `pipeline.py:209` | Writes `schema_version="3"` literal | **Replaced** by import of `SCHEMA_VERSION` from `interaction_log`. |
| `pipeline.py:214` | Writes `event_type` into the record dict | Unchanged shape; value is now one of 4. |
| `interaction_log.py:21,37` | `EventType` literal + field declaration | **Add `SCHEMA_VERSION = "4"` module constant.** Field default switches to `SCHEMA_VERSION`. `EventType` literal is unchanged (already declares all 4). |
| `dashboard_model.py:66` | `gap_rate`: `r.event_type == "gap" or not r.knew_answer` | **`or not r.knew_answer` removed.** |
| `dashboard_model.py:70` | `deflection_rate`: `r.event_type == "deflected"` | Unchanged code; output flips from 0% to a real number. |
| `dashboard_model.py:74` | `refusal_rate`: `r.event_type == "refused"` | Unchanged. |
| `dashboard_model.py:151` | `event_counts`: `Counter(r.event_type for r in self.records)` | Unchanged code; distribution gains real `gap` / `deflected` buckets. |
| `dashboard_model.py:277` | `confident_failure_rate`: `r.event_type == "refused"` (one disjunct) | Unchanged. |
| `failure_feed.py:105` | `classify_failure`: `record.event_type == "refused"` | Unchanged in slice 1. (Slice 2's audit decides whether to add a `deflected` branch and whether `gap` should switch from `not knew_answer` to `event_type == "gap"`.) |
| `flag_detector.py:152` | Repeat-failure filter: `r.event_type in {"deflected", "refused"}` | Unchanged code. **Behaviour changes:** the trip-wire starts catching real `deflected` records. |
| `summarize_failures.py:98` | Group filter: `r.event_type == "deflected"` | Unchanged code. **Behaviour changes:** the deflection group starts surfacing real records. |
| `summarize_failures.py:109` | Prompt body line: `· **Event:** {record.event_type}` | Unchanged. |
| `canary_corpus.py:42,67` | Reads `expected_event_type` from the corpus YAML — corpus-side label, not the live `event_type` | Untouched in slice 1. (Replaced wholesale in slice 4 along with `expected_branch`.) |
| `canary_drift.py:38,58,105,193–198` | `event_type_changed` drift kind compares baseline vs current | Unchanged. **Behaviour changes:** the comparison becomes meaningful per-question once v4 producer is shipped, because baseline + current carry real `gap` / `deflected` values. |
| `sentinel.py:1621,1666` | UI rendering: `record.event_type` in the failure drilldown header and per-turn summary | Unchanged. **Visible:** drilldowns now say `Event: gap` / `Event: deflected` for the records that warrant it. |

### `tests/`

| File | Reads `event_type` for | Slice 1 disposition |
|---|---|---|
| `test_pipeline.py:149,161,187,193,207` | Asserts the producer emits `answered` / `refused` | **Updated.** New tests cover GAP-branch → `gap`; LOGISTICAL-branch → `deflected`; non-GAP branch + GAP_PHRASE in answer → `gap`; non-GAP / non-LOGISTICAL branch + DEFLECTION_MARKER in answer → `deflected`. |
| `test_log_reader.py:19` | Fixture for a v1 `answered` record | Unchanged. |
| `test_log_reader.py` (new) | — | **New test:** `test_read_smart_normalizes_v3_record_with_gap_phrase_to_event_type_gap`. **New test:** `test_read_does_not_apply_deflection_markers_to_v3_records`. |
| `test_interaction_log.py:13` | Round-trip fixture | **Updated** — bump `schema_version` to `"4"` in the canonical fixture. |
| `test_canary_baseline.py:29` | Fixture | Unchanged. |
| `test_canary_runner.py:28,45` | Fixtures + assertion | Unchanged in slice 1; canary corpus rewrite is slice 4. |
| `test_canary_drift.py:35–106,166–171` | Drift detector fixtures | Unchanged. |
| `test_dashboard_model.py:50–80` (`test_gap_rate_unions_knew_answer_false_with_event_type_gap`) | Asserts the `OR not knew_answer` proxy | **Replaced** by `test_gap_rate_is_fraction_of_records_with_event_type_gap` (no `knew_answer` reference). |
| `test_dashboard_model.py:97–107` (`test_deflection_rate_…`) | Already asserts `event_type=="deflected"` | Unchanged. |
| `test_dashboard_model.py:786–795` (`test_event_counts_…`) | Already covers all 4 event types | Unchanged. |
| `test_failure_feed.py:28–47, …` | Synthetic-record fixture | **Updated** — fixtures that pair `knew_answer=False` with `event_type='answered'` to simulate the producer bug get a v3-style replacement (or, where the test is asserting `classify_failure` precedence, switch to v4 records carrying `event_type='gap'`). Slice 2 will rebuild `classify_failure` itself; slice 1 just keeps these tests green. |
| `test_cluster_gaps.py:24,35,80` | Fixtures with `event_type` arg | Same update strategy as `test_failure_feed.py`. |
| `test_summarize_failures.py:25,71,107–116,260,332` | Fixtures with `event_type` arg | Tests already use `event_type='deflected'` directly; unchanged in slice 1. |
| `test_flag_detector.py:21,32,210,273–280` | Fixtures with `event_type` arg | Already uses `'deflected'` / `'refused'` literally; unchanged. |
| `test_sentinel.py:36–44, 484, 551, 630, 657, 969` | UI-rendering fixtures | Unchanged. |
| `test_canary_corpus.py:21, 27, 42, 62, 74` | Corpus-side fixture for `expected_event_type` | Unchanged in slice 1. |
| `test_composer.py` (new test) | — | **New static prompt-drift test:** `test_logistical_behavioural_generic_prompts_reference_a_deflection_marker_literal`. |
| `test_event_classifier.py` (new file) | — | **New module test file** — one test per rule branch (refused / GAP-branch / LOGISTICAL-branch / GAP_PHRASE-in-answer / deflection-marker-in-answer / fallback-answered). |

---

## 3. Field readers — `knew_answer`

| File:line | Read | Slice 1 disposition |
|---|---|---|
| `pipeline.py:206` | Producer writer: `knew_answer = bool(last_answer) and (GAP_PHRASE not in last_answer)` | **Kept.** v3-compat for consumer code that hasn't been migrated yet (slices 2/3 finish the migration). Comment added: "Populated for v3-compat. New code must not read this; removal scheduled for a future v5 schema bump." |
| `interaction_log.py:45` | Field declaration | Unchanged. |
| `dashboard_model.py:66` | `gap_rate` disjunct | **Removed.** |
| `dashboard_model.py:275` | `confident_failure_rate`: `not r.knew_answer` (one disjunct) | **Untouched in slice 1.** Slice 3 audits remaining `knew_answer` reads and removes them; slice 1 stays bounded. |
| `failure_feed.py:48` | Plain-English label string for the `gap` failure mode | Untouched in slice 1; slice 2 rewrites `classify_failure`. |
| `failure_feed.py:107` | `classify_failure`: `if not record.knew_answer: return "gap"` | Untouched in slice 1; slice 2 swaps to `record.event_type == "gap"`. |
| `sentinel.py:1311` | Tooltip text mentions `(knew_answer=False)` | **Updated** to the new definition (drop `knew_answer` reference). |
| `tests/test_pipeline.py:210` | Asserts `knew_answer is True` on a refused turn | Unchanged. |
| `tests/test_failure_feed.py:67–115, …` | Fixture + assertion | Untouched in slice 1; slice 2 rewrites. |
| `tests/test_cluster_gaps.py:54–100, 250–363` | Fixture for live-data gap signal | Untouched in slice 1; slice 2 rewrites. |
| `tests/test_summarize_failures.py:47, 69–134, 168–169, 260, 329` | Fixture | Mostly untouched; one fixture in `test_dashboard_model.py:50–80` does change because the test it backs is being replaced. |
| `tests/test_dashboard_model.py:50–80, 260–273, 471, 524, 567, 596, 691` | Various reads | Only the `gap_rate` test is rewritten in slice 1. The others stay. |
| `tests/test_sentinel.py:48, 129–370, 506, 558, 592, 635, 662, 974` | Fixture | Unchanged in slice 1. |

---

## 4. Metric / UI consumers

### Live tab (Sentinel — Metrics tab, scope of slice 1)

| Metric / UI element | Source | Behaviour change after slice 1 |
|---|---|---|
| `gap_rate` (Outcome block) | `dashboard_model.gap_rate` | Definition narrows from `event_type=='gap' OR not knew_answer` to `event_type=='gap'`. Numerically: producer now emits `gap` for every record the previous proxy was catching plus the GAP-branch records the proxy missed (because GAP-branch answers don't always include the verbatim phrase). **Predicted live value:** ~44.4% on the existing 99-record local log (40 GAP-branch + 4 phrase-bearing non-GAP). The pre-fix proxy reported 9.4%. **The jump is the metric becoming honest, not a regression.** Most of the 40 GAP-branch records are constructive gap-aware answers, which is the correct outcome. The Live tab tooltip is rewritten to say so — see § 6 below. |
| `deflection_rate` (Outcome block) | `dashboard_model.deflection_rate` | Code unchanged. **Predicted live value:** ~7.1% on the existing 99-record local log (4 LOGISTICAL-branch + 3 phrase-bearing non-LOGISTICAL). Pre-fix value was flat 0%. Tooltip rewritten — see § 6. |
| `refusal_rate` (Outcome block) | `dashboard_model.refusal_rate` | Unchanged. ~1% on the existing log. |
| `event_counts` (Outcome block) | `dashboard_model.event_counts` | Distribution gains real `gap` and `deflected` buckets. Already rendered in the UI; no code change needed. |
| Failure drilldown header (Failures tab) | `sentinel.format_failure_drilldown` | The `**Event:** gap` / `**Event:** deflected` line starts surfacing real values for non-`answered`/`refused` records. No code change needed. |

### Live tab tooltips & glossary (Sentinel — `METRIC_GLOSSARY` + `SENTINEL.md`)

| Surface | Slice 1 change |
|---|---|
| `src/sentinel.py:1311` (`Gap rate` tooltip) | Rewrite from `"…knew_answer=False"` to user-semantic phrasing: `"Share of turns where the system either acknowledged it didn't have the information (canonical gap phrase) or produced a structured gap-aware response about an absent skill."` Avoid leaking the producer-rule mechanism into operator-facing copy. |
| `src/sentinel.py:1312` (`Deflection rate` tooltip) | Rewrite from `"Share of BEHAVIOURAL turns that redirected to a STAR anecdote in personal_stories"` to user-semantic phrasing: `"Share of turns where the system politely redirected an out-of-scope question (general coding help, trivia, opinions) rather than answering."` |
| `docs/SENTINEL.md` § Outcome block / `gap_rate` | Rewrite definition to `count(event_type == "gap") / total`. Replace the proxy-caveat paragraph with a paragraph explaining the post-slice-1 producer rule and the GAP-branch contribution. Note that GAP-branch answers count as gap regardless of phrase content (constructive gap-aware answers are still gaps). |
| `docs/SENTINEL.md` § Outcome block / `deflection_rate` | Rewrite definition to `count(event_type == "deflected") / total`. Drop the writer-parity caveat. Replace with one sentence explaining that LOGISTICAL-branch records always count as deflected, and that non-LOGISTICAL deflections are caught via DEFLECTION_MARKERS phrase-matching. |
| `docs/SENTINEL.md` § Outcome block thresholds | `gap_rate` healthy threshold needs revisiting once the new producer is on disk for a week — flag this as a known follow-up; do not change the threshold in slice 1. The current thresholds (≤10% healthy, ≤15% warning) were calibrated against the proxy and will read alert on healthy traffic until reset. **Action:** add a one-line callout in `SENTINEL.md` saying so. (Threshold reset itself is deferred — same pattern as PRD § "Open questions deferred to a future grilling session".) |

### Glossary (`CONTEXT.md`)

| Entry | Slice 1 change |
|---|---|
| `Interaction log` | Update the parenthetical `event_type` value list — already reads `answered \| gap \| deflected \| refused`, so no copy change needed. Update the version-tail note: append `Pre-#42 records lack a producer-side gap/deflected emission and are read with smart-normalize for v3 records carrying GAP_PHRASE.` |
| `Deflection` | Refresh to call out that `event_type='deflected'` is now produced for LOGISTICAL turns as well as `DEFLECTION` rule fires. The `DEFLECTION` rule (BEHAVIOURAL routing) is unchanged; the producer is what changes. |
| `Gap phrase` | Unchanged — still the canonical literal. Add one sentence: "`event_type='gap'` is now emitted whenever the producer's classifier rule fires — see ADR-0003 § event-type classification (post-#42)." |
| (new entry) `event_type` | **Add a glossary entry** with the four values + the producer rule's branch precedence + phrase fallback. Mirrors the existing `Branch` and `Classifier` entries in shape. |
| (new entry / inline) `knew_answer` | **Mark legacy.** Prefix with `**[Legacy as of v4]**`, point to `event_type` as the live signal, link to the v5 removal TODO. |

### `docs/MAP.md` and `docs/pipeline_diagram.mmd`

The runtime pipeline diagram already shows the producer writing the log. **No diagram change needed** — slice 1 doesn't add a new branch, tool, or decision point; it tightens the value computed inside an existing step. (Slice 4 will need a diagram update for the canary outcome derivation; slice 1 does not.)

`uv run python src/system_map.py` should be re-run after the slice lands to refresh the auto-generated module graph (it will pick up the new `event_classifier.py` module).

### `docs/LIMITATIONS.md`

Add `P15` per the PRD's *Companion update*:

> **P15 — TECHNICAL and BEHAVIOURAL graceful-deflect.** TECHNICAL and BEHAVIOURAL branches have graceful-deflect capability when retrieved chunks don't support a claim. Architecture predicted GAP would handle this; in practice non-GAP-routed deflections are correct outcomes. After #42, these are classified as `event_type='deflected'` via the DEFLECTION_MARKERS phrase rule and surface honestly on the Live tab — treat them as expected behaviour, not errors. Trip-wire: a sustained drop in TECHNICAL `event_type='deflected'` co-occurring with a rise in `guardrail_rejection_rate` for fabrication, suggesting the rule loosened its grip on canonical phrasing.

---

## 5. Predicted behaviour change — quantified

Computed against the local interactions log on 2026-05-05. **Live records (non-canary, n=99):**

| Metric | Pre-slice-1 | Post-slice-1 (predicted) | Source signal |
|---|---|---|---|
| `gap_rate` | 9.4% (proxy: `not knew_answer`) | **44.4%** (40 GAP-branch + 4 phrase-bearing) | `event_type=='gap'` only |
| `deflection_rate` | 0.0% (writer never sets) | **7.1%** (4 LOGISTICAL-branch + 3 phrase-bearing) | `event_type=='deflected'` only |
| `refusal_rate` | 1.0% (1/99) | 1.0% (unchanged) | `event_type=='refused'` |
| `event_counts.gap` | 0 | ~44 | producer rule |
| `event_counts.deflected` | 0 | ~7 | producer rule |
| `event_counts.answered` | 98 | ~47 | producer rule |
| `event_counts.refused` | 1 | 1 | producer rule |

**Important:** these numbers are predictions based on running the new rule against the *existing* records' `branch` field + last attempt's `answer` field. On-disk records are never rewritten; only newly-written records carry v4 `event_type`. Pre-v4 records (v1/v2/v3) continue to read with their original `event_type` *plus* the read-time GAP_PHRASE smart-normalize.

**Smart-normalize coverage** (under the generalized `schema_version != "4"` rule):
- 8 v1 live records carrying `GAP_PHRASE` → read as `event_type='gap'` (currently read as `'answered'`).
- 17 v3 canary records carrying `GAP_PHRASE` → read as `event_type='gap'` when the Canary tab is rendered with `include_canary=True`. (No-op for live tabs because canary records are filtered.)
- v2 live records: 0 carry `GAP_PHRASE`; rule is a no-op for them.

**Why generalize from the PRD's v3-only spec:** the PRD's rationale ("pre-fix prompts didn't enforce canonical phrasing for non-GAP_PHRASE deflection") applies equally to v1 and v2. GAP_PHRASE itself has been canonical across all schema versions; the only asymmetry is whether the producer correctly classified records carrying it. Restricting smart-normalize to v3 would leave 8 demonstrably-gap records mis-classified as `answered` indefinitely — patch-style narrowing, not principled. The generalized rule is the correct long-term fix and has the same false-positive surface as v3-only (an answer accidentally embedding the gap phrase in a quote remains an edge case for both rules). Implementing the generalized rule.

### Intermediate-state expectations between slice 1 and slice 2

- `failure_feed.classify_failure` still uses `not record.knew_answer` to label the `gap` mode — slice 1 leaves this untouched. The label and dashboard `gap_rate` will momentarily diverge: dashboard says 44.4%, failure-feed `gap` count says ~8% (the old `not knew_answer` proxy share). Slice 2's audit + rewrite reconciles them.
- `cluster_gaps.extract_gap_questions` reuses `classify_failure`, so it inherits the same divergence — slice 1 leaves this untouched.
- `summarize_failures.select_records_for_group("gap", …)` reuses `classify_failure` — same divergence — until slice 2.
- `summarize_failures.select_records_for_group("deflection", …)` already keys on `event_type=='deflected'` — **slice 1's effect: this group goes from "always empty" to "real deflection records".** The deflection summary file will start carrying real content from the next batch run.
- `flag_detector.detect_repeat_failure`'s `_REPEAT_FAILURE_EVENTS` filter starts catching real `event_type=='deflected'` records — the trip-wire becomes meaningful for the deflected pattern, not just refused.

These intermediate-state effects are documented here so they don't read as regressions during the gap between slice 1 merging and slice 2 starting.

---

## 6. Workarounds removed

Concrete list of dead-code paths and proxies that slice 1 deletes:

1. `dashboard_model.gap_rate` — `or not r.knew_answer` disjunct removed (line 66). Comment block at lines 60–66 deleted.
2. `dashboard_model.gap_rate` test rewritten (`tests/test_dashboard_model.py:50–80`) — the test name and body that asserted the proxy union are replaced by a test of the direct `event_type == "gap"` definition. The proxy fixture (`event_type="answered", knew_answer=False`) goes away.
3. `pipeline.py:202` inline ternary — replaced by `classify_event_type(branch_name, final_answer)`.
4. `src/sentinel.py:1311–1312` glossary tooltip strings — rewritten to drop `knew_answer=False` and `BEHAVIOURAL turns that redirected to a STAR anecdote` (the latter is wrong: it conflates the `DEFLECTION` rule with `event_type='deflected'`; LOGISTICAL turns are the more common deflection source, and BEHAVIOURAL deflections are the rarer subset triggered by the rule).
5. `docs/SENTINEL.md` proxy-caveat paragraphs for `gap_rate` and `deflection_rate` — deleted, replaced by one-paragraph definitions of the producer rule.

Workarounds **not** removed in slice 1, by design:

- `dashboard_model.confident_failure_rate` — still reads `not r.knew_answer` (line 275). Slice 3 finishes the `knew_answer` consumer audit.
- `failure_feed.classify_failure` — still keys `gap` on `not r.knew_answer`. Slice 2.
- `cluster_gaps.extract_gap_questions` — proxies through `classify_failure`. Slice 2.
- `summarize_failures.select_records_for_group("gap", …)` — proxies through `classify_failure`. Slice 2.
- `failure_feed.FAILURE_MODE_LABELS["gap"] = "unknown answer (knew_answer=false)"` — string label. Slice 2.
- `pipeline.py:206` — `knew_answer` is still written for v3-compat. Removal of the writer is a future v5 bump (see `CONTEXT.md` legacy marking and the TODO note added in slice 3).

---

## 7. New code surface

| File | New | Purpose |
|---|---|---|
| `src/event_classifier.py` | yes | Pure function `classify_event_type(branch, final_answer) -> EventType`. Imports `GAP_PHRASE` and `DEFLECTION_MARKERS` from `rules`. No I/O. |
| `tests/test_event_classifier.py` | yes | Six tests, one per rule branch. No mocks. |
| `src/rules.py` | edit | New constant `DEFLECTION_MARKERS: tuple[str, ...] = ("…",)`. Distinct from existing `rules.DEFLECTION` (which is the BEHAVIOURAL-branch rule body). Comment in the file calls out the distinction. |
| `src/composer.py` | edit | Append a `DEFLECTION_INSTRUCTIONS` block (analogous to the GAP_PHRASE line in `GENERATOR_FRAMING`) for branches in `{LOGISTICAL, BEHAVIOURAL, GENERIC}`. Keeps GAP and TECHNICAL framing as-is. |
| `tests/test_composer.py` | edit | Add static prompt-drift test asserting each non-GAP / non-TECHNICAL branch's composed prompt contains at least one literal `DEFLECTION_MARKERS` substring. |
| `src/log_reader.py` | edit | Smart-normalize: if a record carries `schema_version != SCHEMA_VERSION` (any pre-v4 record) and the last attempt's accepted answer text contains `GAP_PHRASE`, override the read-time `event_type` to `"gap"`. On-disk record never mutated. Generalized from PRD's v3-only spec (see § 5). |
| `tests/test_log_reader.py` | edit | New test `test_read_smart_normalizes_pre_v4_record_with_gap_phrase_to_event_type_gap` (covers v1/v2/v3 in a parametrized form). New test `test_read_does_not_apply_deflection_markers_to_pre_v4_records`. New test `test_read_passes_v4_records_through_without_normalize`. |
| `src/pipeline.py` | edit | Replace inline ternary with `classify_event_type(...)`. Replace literal `"3"` schema-version write with import of `SCHEMA_VERSION` from `interaction_log`. Update comment at lines 203–205 to mark `knew_answer` legacy. |
| `tests/test_pipeline.py` | edit | New tests covering each rule branch's emission. Existing tests' `event_type` assertions stay valid for the `answered` and `refused` cases. |
| `src/interaction_log.py` | edit | Add `SCHEMA_VERSION = "4"` module constant. Field default switches to `SCHEMA_VERSION`. |
| `tests/test_interaction_log.py` | edit | Update fixture `schema_version` to `"4"`. |
| `src/dashboard_model.py` | edit | Drop the `or not r.knew_answer` disjunct from `gap_rate`. |
| `tests/test_dashboard_model.py` | edit | Replace the `test_gap_rate_unions_…` test with one asserting the direct definition. |
| `src/sentinel.py` | edit | Tooltip string updates only. |
| `docs/SENTINEL.md` | edit | Definition + caveat rewrites for `gap_rate` and `deflection_rate`. Threshold-reset callout. |
| `CONTEXT.md` | edit | Glossary updates: new `event_type` entry, refresh on `Deflection` and `Gap phrase`, legacy mark on `knew_answer`. |
| `docs/LIMITATIONS.md` | edit | Add `P15` per § 4 above. |

---

## 8. Design philosophy — DEFLECTION_MARKERS as a prompt↔producer contract

`DEFLECTION_MARKERS` is **not** a detector vocabulary that observes how the model phrases deflections in the wild and chases the moving target. That framing leads to whack-a-mole: a model upgrade, a prompt edit, or a temperature shift produces a new phrasing and the classifier silently regresses.

The principled framing: the markers are a **bidirectional contract** between two surfaces that both `import` the same constant.

1. **Composer prompt (the producer-side instruction).** The LOGISTICAL / BEHAVIOURAL / GENERIC composer prompts instruct the model to begin out-of-scope redirects with one of the canonical phrases. The model's job is to comply with the rule, not to invent new deflection phrasings.
2. **`event_classifier` (the producer-side classifier).** Reads the same constant and matches the literal substrings on the answer text.
3. **Static prompt-drift test.** Asserts each non-GAP / non-TECHNICAL branch's composed prompt contains at least one literal `DEFLECTION_MARKERS` substring. This is the forcing function that prevents the contract from drifting silently — a future prompt edit that drops the canonical phrasing fails the test before it ships.
4. **Guardrail (downstream).** If the model emits a deflection that doesn't follow the contract, the *guardrail* should catch it as a rule-following failure (not the producer classifier's job to recover).

The list of markers is therefore not "what we have observed" but "what we instruct the model to use". The transcripts informed the choice of phrasings (start from idiomatic-recruiter-bar redirects rather than invented vocabulary), but the contract — once locked — is what governs.

This framing has direct consequences for how we handle edge cases:

- **Apostrophe variants (straight `'` vs curly `’`).** Composer prompt uses a straight apostrophe; producer matches the straight form. If the model emits a curly apostrophe, the contract is broken — that's a rule-following miss, surfaced naturally as a false-negative deflection in the data. Don't add string-normalization patches; the right response (if it becomes material) is to tighten the prompt rule, not to widen the matcher. Same logic applies to model-rewording, paraphrase, decorated phrasings.
- **Future model upgrades.** A new model is on-rule until proved otherwise; if the static test passes (canonical phrasing still in the prompt) and live `deflection_rate` doesn't collapse, the contract is intact. If it collapses, the *prompt rule* is what tightens, not the matcher.
- **New deflection shape (e.g. a future "I can connect you with Alejandro for that" pattern).** Add to the constant + add to the prompt rule + the static test enforces the addition. Single edit, single source of truth.

`DEFLECTION_MARKERS` is therefore a small, stable, deliberately-chosen set of canonical phrases — not a growing list of observed variants.

### The proposed list

Mined from `data/logs/interactions.jsonl` to seed the contract from idiomatic-recruiter-bar redirects rather than invented vocabulary. Frequency in parentheses (last-attempt answer text matches across 99 live + 226 canary records).

```python
DEFLECTION_MARKERS: tuple[str, ...] = (
    "I'm here to answer questions",  # production prefix; 11 hits
    "I'm here to help with",         # 1
    "I'm here to provide",           # 1 (also catches "here to provide information")
    "outside the scope",             # 4 (also catches "outside the scope of …")
    "falls outside",                 # 5 (catches "falls outside the scope", "falls outside what", "falls outside my scope")
    "not in a position to answer",   # 2
)
```

Six entries; small enough that adding a new shape is a deliberate edit, large enough to cover the canonical patterns. Ordered most-common first so the substring scan short-circuits fast on typical deflections.

---

## 9. Composer prompt edits — concrete

`src/composer.py::GENERATOR_FRAMING` already instructs `respond with the gap phrase: "{GAP_PHRASE}"` for absent-context cases. Add a parallel construct for out-of-scope deflection.

### Approach

Extract a new `DEFLECTION_INSTRUCTIONS` rule body keyed under `RULES` (mirroring `GAP_PHRASE`'s home in `CALIBRATION_LADDER` rather than living inline in framing) so it composes only on the branches that need it. Wire it onto `LOGISTICAL`, `BEHAVIOURAL`, and `GENERIC` via `BranchSpec.branch_rules`.

Body sketch (final wording confirmed during implementation):

```text
## Out-of-scope redirects
When the visitor's question is outside the assistant's scope (general coding help,
trivia, personal opinions, requests to roleplay), produce a polite redirect rather
than answering. Begin the redirect with one of these canonical phrases so the
producer can classify the outcome consistently:

- "I'm here to answer questions about Alejandro's…"
- "I'm here to help with…"
- "I'm here to provide…"
- "outside the scope of…"
- "falls outside…"
- "not in a position to answer…"

Do not fabricate. Do not lecture. One short paragraph; offer to discuss
Alejandro-related topics instead.
```

Branches affected:

- `GENERIC` — out-of-scope catches the largest share (general coding help, trivia, world questions).
- `LOGISTICAL` — every LOGISTICAL turn is already a deflection per the producer's branch rule, but the prompt still benefits from canonical phrasing for consistency.
- `BEHAVIOURAL` — already deflects via the `DEFLECTION` rule when no story matches; this aligns the wording.

`GAP` and `TECHNICAL` do *not* receive the deflection instruction — gaps go through the GAP_PHRASE; tool-eligible technical turns either answer with substance, gap-acknowledge with calibration, or fall through to the existing `tool_rules` framing.

### Static prompt-drift test (slice 1, new)

```python
def test_logistical_behavioural_generic_prompts_reference_a_deflection_marker_literal(real_composer):
    for branch in ("LOGISTICAL", "BEHAVIOURAL", "GENERIC"):
        prompt = real_composer.compose([branch], "generator")
        assert any(marker in prompt for marker in DEFLECTION_MARKERS), (
            f"branch={branch} prompt is missing every DEFLECTION_MARKERS literal — "
            "a future prompt edit broke event-type classification"
        )
```

This is the forcing function that prevents prompt drift from silently breaking the producer's phrase-fallback rule.

---

## 10. Risk register for this slice

| Risk | Mitigation |
|---|---|
| The composer prompt change degrades answer quality on LOGISTICAL/BEHAVIOURAL/GENERIC turns. | Smoke-test 5–10 representative live questions per branch from `interactions.jsonl` after the slice lands; compare answer quality side-by-side against pre-slice. |
| The `DEFLECTION_MARKERS` set is too narrow and many deflections classify as `answered`. | Mined from real transcripts; covers 19/99 live records that should classify as deflected. After slice 1 lands, re-check the marker hit-rate weekly; expand the set if a new phrasing emerges. |
| The `DEFLECTION_MARKERS` set is too broad and substantive answers get misclassified as `deflected`. | Markers chosen to be sentence-prefix patterns and idiomatic redirects — unlikely to appear inside a substantive in-scope answer. The static prompt-drift test asserts the canonical literal lands in the prompt; the producer rule applies the same literal to the answer; both directions stay in sync. |
| `gap_rate` jumping from 9.4% to ~44% reads as a regression to anyone not reading this audit. | Document in PR description, callout in `SENTINEL.md`, and predicted-value box in this doc § 5. |
| Slice 1 + slice 2 intermediate divergence (dashboard `gap_rate` and failure-feed `gap` mode out of sync). | Documented in § 5; resolved by slice 2's audit. |

---

## 11. Pre-flight checklist

- [ ] Test suite green pre-implementation (462 collected as of 2026-05-05).
- [ ] After implementation, run `uv run python src/module_health.py` — `event_classifier.py` must register with a matching `tests/test_event_classifier.py`.
- [ ] After implementation, run `uv run python src/system_map.py` to refresh the module graph (no diagram edit needed — see § 4).
- [ ] PR description links back to this audit and to PRD #41.
- [ ] PR description calls out the predicted `gap_rate` / `deflection_rate` jumps so operator review reads them as intended.

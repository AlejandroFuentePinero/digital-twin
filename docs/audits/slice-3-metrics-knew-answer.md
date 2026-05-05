# Slice 3 — Metrics tab cleanup + `knew_answer` legacy (audit)

**Issue:** [#44](https://github.com/AlejandroFuentePinero/digital-twin/issues/44)
**PRD:** [#41](https://github.com/AlejandroFuentePinero/digital-twin/issues/41) — see § *Slice 3* and § *Audit-first discipline*.
**Prior slice audits:** [`slice-1-producer-fix.md`](./slice-1-producer-fix.md), [`slice-2-failure-feed.md`](./slice-2-failure-feed.md).
**Status:** Pre-implementation. This document lands before any code change. The PR for slice 3 includes both this audit and the implementation; reviewers verify the change matches the predictions below.

---

## 1. Scope

Slice 3 closes out the consumer-side `knew_answer` migration and reframes the live tool-call metric so its name stops implying a target the system isn't trying to hit. Two scoped pieces, plus the writer-side legacy marking.

**Piece A — last `knew_answer` consumer-side read removed.**

- `src/dashboard_model.py::confident_failure_rate` — the inner `_failed` predicate's `not r.knew_answer` disjunct (line 274) is replaced with `r.event_type in {"gap", "refused"}`. The trailing `r.event_type == "refused"` disjunct collapses into the set membership; the rejected-attempt disjunct stays.
- After this slice, **zero** `knew_answer` reads remain in `src/`. The producer keeps populating the field for v3-record consumer compat; removal of the writer is a future v5 schema bump.
- `src/pipeline.py:204–208` writer comment refreshed: drops the "slices 2 and 3 still migrating" line; lands a "Consumer migration complete" line plus a TODO pointer to the v5 removal.
- `CONTEXT.md::Interaction log` legacy note rewritten: drops the "only remaining reader is `dashboard_model.confident_failure_rate`" half-sentence; lands "all consumer code now reads Event type directly".

**Piece B — `technical_tool_uptake_rate` renamed and reframed as descriptive.**

The metric is **already** orientation-only (`metric_status.THRESHOLDS` has no entry for it; demoted in Session 39 — see `metric_status.py:56`). The remaining normative residue is in the **name** itself — "uptake" implies a target — and in operator-facing copy that still discusses thresholds and warranted-uptake gaps.

- Rename `dashboard_model.technical_tool_uptake_rate` → **`dashboard_model.technical_tool_call_rate`**. Selection rationale in § 2.
- Update every reference: `METRIC_GETTERS` registry key, `sentinel.py` (FRIENDLY_BANNER_LABELS, METRIC_SPECS, METRIC_LABELS, THEMATIC_BLOCKS), `metric_status.py` historical comment, `docs/SENTINEL.md` glossary + runbook header, `docs/LIMITATIONS.md::P8` (live-metric mentions), `docs/TODO.md` slice-3 description, `tests/test_dashboard_model.py` test name + body.
- Reframe the `docs/SENTINEL.md::technical_tool_call_rate` glossary entry: drop the "no threshold (Session 39 demotion)" historical reference and the "uptake" framing; replace with one paragraph that names the property (rate of TECHNICAL turns invoking `fetch_project_readme`) and notes that it is descriptive — useful for direction-of-change reads, but not a target.
- Sentinel UI label changes: METRIC_SPECS row "Tool uptake (TECHNICAL)" → **"Tool calls / TECHNICAL turn"**; METRIC_LABELS map (used by Trend Explorer y-axis) updates to match; FRIENDLY_BANNER_LABELS "Tool usage" → **"Tool calls per TECHNICAL turn"** (banner is unaffected today because the metric has no threshold and is filtered out at line 1190, but keep the entry coherent for the day someone re-introduces a threshold for a different reason).

**Piece C — writer-side legacy marking (housekeeping).**

- `pipeline.py:204–208` comment: as above.
- `CONTEXT.md::knew_answer` glossary status: it already carries `**[Legacy as of v4]**` (slice 1 added it). Slice 3 confirms the marking is current and tightens the wording — "all consumer code now reads `event_type` directly" replaces the slice-2-era half-state framing.

**Out of scope** (deliberately, per slice contract):

- The canary-side `tool_uptake_on_warranted(corpus)` metric is **not** renamed. PRD #41 § *Slice 4* removes the entire `branch_match_rate` / `tool_uptake_on_warranted` pair as part of the canary recalibration (the new contract is `outcome_accuracy` / `keyword_coverage` / `red_flag_rate`). Renaming a metric in slice 3 only to delete it in slice 4 is patch-style anticipation; let slice 4 own its surface end-to-end.
- The `pipeline.py:209` writer is **not** removed — only the comment is refreshed. Removal is a future v5 schema bump.
- The `interaction_log.py:51` `knew_answer` field declaration stays — same reason.
- `CONTEXT.md::knew_answer` glossary entry: confirm marking is current; no structural change. (`CONTEXT.md` is gitignored locally per Session 44; edits live in the working tree.)

---

## 2. The rename — `technical_tool_uptake_rate` → `technical_tool_call_rate`

PRD #41 user-story #1 frames the principle: *"every metric on every Sentinel tab to mean exactly what its label says, so that I do not have to mentally translate."* "Uptake" carries a normative payload — "we want this to go up" — that the metric isn't trying to express. The reframe makes the name purely descriptive.

### Candidates considered

| Candidate | Verdict |
|---|---|
| `technical_tool_call_rate` | **Selected.** Parallel to the existing `tool_call_count` (volume) and `tool_call_success_rate` (quality). Triple becomes `count` / `rate` / `success_rate` — orthogonal axes over the same underlying tool-call event. "Call rate" is a literal read: rate of tool calls per TECHNICAL turn. |
| `technical_tool_share` | Acceptable but unusual phrasing in this codebase (no other "share" metrics; closest is `latency_with_share` which uses "share" in a different sense — share of a tail). Adds a second meaning of "share" within the same module, which is friction. |
| `technical_tool_use_rate` | "Use" is mild but still slightly load-bearing — "low tool use" reads as a deficit. "Call" is purely mechanical. |
| `technical_tool_invocation_rate` | Verbose. Same content as `call_rate` with one more syllable per surface. |
| `technical_branch_tool_call_rate` | Redundant — "TECHNICAL branch" and "tool call" already disambiguate; the property already lives on `DashboardModel`. Long names add cognitive load on the Metrics tab grid. |

**Selected:** `technical_tool_call_rate`. Naming consistency with the existing tool-block metrics is the load-bearing reason; the descriptive-not-normative framing is the reframing reason.

### What the rename does NOT change

- Definition is unchanged: `count(branch == "TECHNICAL" AND tool_calls != []) / count(branch == "TECHNICAL")`.
- Numerical value unchanged. Predicted live value: **66.7%** on the current 99-record local log (last verified Session 39; identical denominator and numerator in v4).
- No threshold added. Stays orientation-only — `metric_status.THRESHOLDS` has no entry, so no banner / no Trends y-axis threshold ribbon. (`THEMATIC_BLOCKS["Tool use"]` still includes the renamed key so the Trend Explorer can plot it without a threshold reference line — same surfacing as today.)
- Denominator caveat persists. The live metric's denominator is "all TECHNICAL turns" not "TECHNICAL turns warranting a tool call"; the canary-side `tool_uptake_on_warranted` (slice 4 will rebuild it) is the surface with the clean denominator. The rename does not pretend to fix `LIMITATIONS::P8` — it just stops the name itself from misleading.

### Operator-facing copy reframing

| Surface | Pre-slice-3 | Post-slice-3 |
|---|---|---|
| Metrics tab grid row label | `Tool uptake (TECHNICAL)` | `Tool calls / TECHNICAL turn` |
| Trends y-axis label (`METRIC_LABELS`) | `Tool uptake (TECHNICAL)` | `Tool calls / TECHNICAL turn` |
| FRIENDLY_BANNER_LABELS | `Tool usage` | `Tool calls per TECHNICAL turn` |
| `SENTINEL.md` glossary header | `technical_tool_uptake_rate` | `technical_tool_call_rate` |
| `SENTINEL.md` glossary body | "What it proxies: whether the tool surface is being used as designed", "Proxy caveats", "No threshold (Session 39 demotion)" | "Definition", "What it measures: rate of TECHNICAL turns invoking `fetch_project_readme`", "Read it as direction-of-change orientation, not a target", denominator-caveat note pointing to the canary-side counterpart (slice 4) |
| `SENTINEL.md` runbook header | `### technical_tool_uptake_rate drop` | `### technical_tool_call_rate drop` (body unchanged — drop is still meaningful as orientation, even without a threshold) |
| `LIMITATIONS::P8` references | `technical_tool_uptake_rate` (3 mentions) | `technical_tool_call_rate` |

---

## 3. Field readers — `knew_answer`

Every read of `knew_answer` in `src/` and `tests/` today, and what slice 3 does to each.

### `src/`

| File:line | Read | Slice 3 disposition |
|---|---|---|
| `dashboard_model.py:274` | `confident_failure_rate._failed`: `not r.knew_answer` | **Removed.** Replaced by `r.event_type in {"gap", "refused"}` (which subsumes the existing `r.event_type == "refused"` disjunct on line 276). |
| `dashboard_model.py:276` | `confident_failure_rate._failed`: `r.event_type == "refused"` | **Subsumed** into the new `event_type in {"gap", "refused"}` predicate above. Single disjunct, not two. |
| `pipeline.py:209` | Producer writer: `knew_answer = bool(last_answer) and (GAP_PHRASE not in last_answer)` | **Kept.** Comment block at lines 204–208 is rewritten to reflect post-slice-3 state. |
| `pipeline.py:237` | `"knew_answer": knew_answer` | Unchanged — still written. |
| `interaction_log.py:51` | Field declaration | Unchanged. |
| `failure_feed.py:113` | Module docstring footer note: `"...the knew_answer proxy is gone."` | Unchanged — accurate post-slice-2. |
| `dashboard_model.py:62` | Comment in `gap_rate` body referencing pre-#42 proxy | Unchanged — slice 1 added it; still accurate. |

### `tests/`

| File | Reads `knew_answer` for | Slice 3 disposition |
|---|---|---|
| `test_dashboard_model.py:28, 65, 78` | `_r` fixture builder default + parameter | **Kept** as a fixture parameter (the field still exists and tests still need to round-trip it). Default value stays `True` to model the v4 producer's typical write. |
| `test_dashboard_model.py:50–86` | `test_gap_rate_is_fraction_of_records_with_event_type_gap` — discriminator records | **Unchanged.** This test was rewritten in slice 1 with discriminators (`event_type='answered'` + `knew_answer=False`) precisely to force the workaround removal. The test still passes because `gap_rate` doesn't read `knew_answer` — slice 3 has no work here. |
| `test_dashboard_model.py:267–288` (`test_confident_failure_rate_counts_high_confidence_failures`) | Asserts the `not r.knew_answer` disjunct | **Rewritten.** New test name: `test_confident_failure_rate_counts_high_confidence_gap_refused_or_retry`. The fixture replaces the `knew_answer=False` discriminators with `event_type='gap'` discriminators and adds a v4-specific case: a confident-and-deflected record that **must not** count (deflected is not a failure mode for this metric — see § 4). |
| `test_dashboard_model.py:229, 492, 539, 686, 713` | Round-trip fixtures with `knew_answer=True` default | Unchanged (the field round-trips on the writer). |
| `test_dashboard_model.py:728, 740` | Two fixtures with `knew_answer=False` | Unchanged — these are canary-window tests that don't exercise `confident_failure_rate`; they round-trip the field unchanged. |
| `test_pipeline.py:281` | Asserts the writer still emits `knew_answer is True` on a refused turn whose last generated answer wasn't the gap phrase | **Unchanged.** Producer-side contract is unchanged; this test pins the v4 writer's compat behaviour. Comment at line 173 (`"proxied through not knew_answer"`) is refreshed to drop the now-dead "proxy" framing. |
| `test_pipeline.py:264, 280` | Comments in the refused-turn test | Refreshed copy: drop the "knew_answer reflects whether the last generated answer was a real answer" framing in favour of "knew_answer is still written for v3-record consumer compat; consumers read event_type directly". |
| `test_failure_feed.py`, `test_cluster_gaps.py`, `test_summarize_failures.py`, `test_flag_detector.py`, `test_sentinel.py` | Various fixture sites carrying `knew_answer=...` defaults / overrides | Unchanged. Slice 2 already migrated every consumer-side assertion off `knew_answer`; the surviving fixture passes are round-trip-only. |
| `test_canary_baseline.py:37, test_canary_drift.py:61, test_canary_runner.py:54, test_log_reader.py:26, test_interaction_log.py:20` | Round-trip fixtures with `knew_answer=True` | Unchanged. |

After slice 3 lands, `git grep -nE "not record.knew_answer|not r.knew_answer|knew_answer\\s*=\\s*False" src/` should return **zero hits** in `src/`. Test fixtures continue to round-trip the field — that's the right scope; the field still exists on the schema.

---

## 4. The `confident_failure_rate` rewrite — semantic walk-through

### Today

```python
def confident_failure_rate(self, threshold: float = HIGH_CONFIDENCE_THRESHOLD) -> float:
    def _failed(r: InteractionRecord) -> bool:
        return (
            not r.knew_answer
            or any(not a.get("is_acceptable", True) for a in r.attempts)
            or r.event_type == "refused"
        )
    return self._rate_of(lambda r: r.classification_confidence >= threshold and _failed(r))
```

### Post-slice-3

```python
def confident_failure_rate(self, threshold: float = HIGH_CONFIDENCE_THRESHOLD) -> float:
    # A failure here is any of (gap | refused | guardrail-rejected attempt).
    # Deflected is NOT a failure: a confident deflection on an out-of-scope
    # question is correct system behaviour. Issue #35 'Detection gap' framing
    # holds — the metric catches misroutes that low_confidence_rate is blind to.
    def _failed(r: InteractionRecord) -> bool:
        return (
            r.event_type in {"gap", "refused"}
            or any(not a.get("is_acceptable", True) for a in r.attempts)
        )
    return self._rate_of(lambda r: r.classification_confidence >= threshold and _failed(r))
```

### Why `event_type in {"gap", "refused"}` is the correct semantic replacement

The pre-#42 proxy `not r.knew_answer` was true when (a) `last_answer` was None (refused) or (b) the answer text contained `GAP_PHRASE`. The trailing `r.event_type == "refused"` disjunct was redundant under that proxy — refused turns always had `knew_answer = False` because `bool(None) is False`.

In v4 land, the producer rule emits `event_type='gap'` for *both* the GAP_PHRASE-bearing case **and** GAP-branch turns whose answers don't contain the literal phrase (constructive gap-aware responses). The pre-v4 proxy missed the latter — confident GAP-branch turns with substantive gap-aware answers were *not* counted as failures, even though they should be (the classifier was sure, the system gap-acknowledged correctly, but the *pattern* — repeated confident gap-acknowledgements on what should be answerable questions — is exactly what this metric is designed to catch per issue #35).

So the rewrite produces the metric the original design intended: **a confident gap-acknowledgement counts as a confident failure regardless of whether the answer contains the canonical phrase.**

### Why deflected does NOT count

`event_type='deflected'` is a correct out-of-scope redirect — confident or not, it's the right outcome. Slice 2's audit § 2 made this disposition for the failure feed (deflected lands at the lowest severity tier, marked "informational, not a defect"). The same framing applies here: a confident deflection on a trivia question or a "what's your favourite colour" question is the system doing what it's supposed to do, not failing.

If a future grilling session decides confident deflections *are* operator-actionable (e.g. as a signal that the classifier is over-confident on out-of-scope routing), that's a separate metric — not a quiet expansion of `confident_failure_rate`. Keep the contract narrow.

### Predicted behaviour change

Computed against the local 99-record live log (all pre-v4; slice 1's smart-normalize upgrades 8 records to `event_type='gap'`):

| Surface | Pre-slice-3 reading | Post-slice-3 reading | Source signal |
|---|---|---|---|
| `confident_failure_rate(0.8)` | unchanged across the slice on the current log — all pre-v4 records that had `knew_answer=False` also have post-normalize `event_type='gap'` (they're the same 8 records that contain GAP_PHRASE), and the only refused record carries `event_type='refused'` directly | **identical numerical value** on the current log; the contract switches to read `event_type` directly | `event_type in {"gap", "refused"}` ∪ rejected-attempt disjunct |

**Slice 3's change to `confident_failure_rate` is identity-preserving on the current log.** The structural change matters: under the new contract, future v4 traffic where the producer emits `event_type='gap'` for GAP-branch responses *without* the canonical phrase will start counting toward `confident_failure_rate` — the metric becomes honest in the same way `gap_rate` did in slice 1.

### Why this matters more once v4 traffic accumulates

Predicted v4-projected reading (every record re-emitted under v4 producer; cf. slice 1's audit § 5):

- `dashboard_model.confident_failure_rate(0.8)` will rise to roughly the same proportion as the v4-projected `gap_rate` × confidence-share — if the classifier is consistently confident on GAP-branch routing (as session 42's canary baseline indicated, `branch_match_rate=78.7%`), expect `confident_failure_rate` to climb meaningfully as v4 traffic lands. **This is the metric becoming honest, not a regression.**
- Threshold band stays unchanged (`metric_status.THRESHOLDS["confident_failure_rate"] = healthy 0.03 / warning 0.07`). Like `gap_rate`'s band post-slice-1, this band was calibrated against the pre-v4 proxy and will likely read alert on healthy v4 traffic. Same operator-runbook pattern: **flag the band as descriptive-not-actionable** until a week of v4 traffic accumulates and the operator sets a new healthy band.

---

## 5. Field readers — `technical_tool_uptake_rate`

Every reference to the property name (`src/`, `tests/`, `docs/`), and what slice 3 does to each.

### `src/`

| File:line | Reference | Slice 3 disposition |
|---|---|---|
| `dashboard_model.py:213–218` | Property definition | **Renamed** to `technical_tool_call_rate`. Definition body unchanged. |
| `dashboard_model.py:236` | Docstring on `tool_uptake_on_warranted` referencing the live metric | **Updated** — points to `technical_tool_call_rate` (rename only). The "noisy denominator" framing is unchanged because slice 4 owns the canary-side rebuild. |
| `dashboard_model.py:247` | Docstring on `tool_call_count` referencing the live metric | **Updated** — `"Pairs with technical_tool_call_rate (rate) and tool_call_success_rate (quality)"`. |
| `dashboard_model.py:377` | `METRIC_GETTERS["technical_tool_uptake_rate"]` | **Renamed key** to `"technical_tool_call_rate"`. Lambda body now reads `m.technical_tool_call_rate`. |
| `metric_status.py:56–64` | Historical comment block explaining the Session 39 demotion | **Updated** — references the renamed metric. Body simplified: keep the "denominator includes turns that don't warrant a tool call" caveat (still load-bearing); drop the "demoted to orientation" historical framing (the metric has been orientation-only for many sessions; the comment doesn't need to keep fighting the past). |
| `sentinel.py:1177` | `FRIENDLY_BANNER_LABELS["technical_tool_uptake_rate"] = "Tool usage"` | **Renamed key** to `"technical_tool_call_rate"`; value updated to `"Tool calls per TECHNICAL turn"`. (Still filtered out at line 1190 because the metric has no threshold; entry kept coherent.) |
| `sentinel.py:1284` | METRIC_SPECS row: `("Tool uptake (TECHNICAL)", None, lambda m: m.technical_tool_uptake_rate, _fmt_pct)` | **Updated** — display label `"Tool calls / TECHNICAL turn"`, lambda body `m.technical_tool_call_rate`. Comment at lines 1282–1283 refreshed. |
| `sentinel.py:2293` | `METRIC_LABELS["technical_tool_uptake_rate"] = "Tool uptake (TECHNICAL)"` | **Renamed key** to `"technical_tool_call_rate"`; value `"Tool calls / TECHNICAL turn"`. |
| `sentinel.py:2305` | `THEMATIC_BLOCKS["Tool use"] = ["technical_tool_uptake_rate"]` | **Renamed entry** to `"technical_tool_call_rate"`. |
| `sentinel.py:2046, 2085, 2087, 2088` | `tool_uptake_on_warranted` (canary-side, distinct method) | **Untouched.** Slice 4 owns the canary surface. |

### `tests/`

| File | Reference | Slice 3 disposition |
|---|---|---|
| `test_dashboard_model.py:431–445` | `test_technical_tool_uptake_rate_is_tool_use_share_of_technical_turns` | **Renamed** to `test_technical_tool_call_rate_is_tool_call_share_of_technical_turns`. Body asserts `model.technical_tool_call_rate == 2 / 3`. Docstring updated to drop "uptake" framing. |
| `test_dashboard_model.py:777–799` | `test_tool_uptake_on_warranted_uses_clean_denominator` | **Untouched.** Canary-side, slice 4. |
| `tests/test_metric_status.py:141–154` | Asserts every key in `THRESHOLDS` is mentioned in `SENTINEL.md` | **Untouched.** `technical_tool_uptake_rate` was never in `THRESHOLDS` (orientation-only); nothing to update on the test side. The `SENTINEL.md` rename happens for human-readability, not for this test. |
| `tests/test_sentinel.py:33` | `from metric_status import THRESHOLDS` | Unchanged — uses THRESHOLDS only for orchestration; doesn't reference `technical_tool_uptake_rate` literally. |

### `docs/`

| File:line | Reference | Slice 3 disposition |
|---|---|---|
| `docs/SENTINEL.md:179` | Section header `#### technical_tool_uptake_rate` | **Renamed** to `#### technical_tool_call_rate`. Body rewritten per § 2. |
| `docs/SENTINEL.md:263` | Operator caveats table — "Tool uptake on warranted 38.5%" entry referencing the live metric in the right-hand column | **Untouched.** This row describes the *canary* finding (`tool_uptake_on_warranted=38.5%`); the live-metric mention in the rightmost cell is parenthetical. The row is owned by slice 4 (canary recalibration). |
| `docs/SENTINEL.md:353` | Canary panel description: `"…fixes LIMITATIONS::P8's noisy denominator on the live technical_tool_uptake_rate"` | **Updated** — rename only: `"…on the live technical_tool_call_rate"`. (The full canary recalibration sentence is slice 4's surface.) |
| `docs/SENTINEL.md:457` | Runbook section `### technical_tool_uptake_rate drop` | **Renamed** header to `### technical_tool_call_rate drop`. Body unchanged — the drop runbook is still meaningful as orientation. |
| `docs/LIMITATIONS.md:268` | Trip-wire #2: `"…Sentinel's technical_tool_uptake_rate + Trend Explorer…"` | **Updated** — rename. |
| `docs/LIMITATIONS.md:277` | `"The aggregate technical_tool_uptake_rate exists today; the question-shape breakdown is not yet built…"` | **Updated** — rename. |
| `docs/LIMITATIONS.md:279` | `"Live technical_tool_uptake_rate keeps its noisy denominator…"` | **Updated** — rename. |
| `docs/TODO.md:10` | Slice 3 description: `"…reframes technical_tool_uptake_rate as descriptive…"` | **Updated** — entry refreshed to reflect post-slice-3 state (rename happened, descriptor confirmed). |
| `docs/DECISIONS.md` retrospective entries | Multiple historical references to `technical_tool_uptake_rate` (Sessions 39, 40, 42 etc.) | **Untouched.** Historical record convention — same pattern as slice 1 (`knew_answer` references in pre-#42 session entries kept as-is). |
| `CONTEXT.md::Interaction log` | "As of slice 2 of #41 the only remaining reader is `dashboard_model.confident_failure_rate`…" | **Rewritten** — drop the "only remaining reader" half-sentence; land "all consumer code now reads Event type directly". `CONTEXT.md` is gitignored locally; edits live in the working tree per Session 44 convention. |
| `CONTEXT.md::knew_answer` entry (if present in working-tree edits) | `**[Legacy as of v4]**` marker | **Confirmed current.** Slice 3 verifies the marking is in place; tightens wording if needed. |

---

## 6. Workarounds removed

Concrete list of dead-code paths and proxies that slice 3 deletes:

1. `dashboard_model.confident_failure_rate._failed` — `not r.knew_answer` disjunct (line 274) deleted; replaced by `r.event_type in {"gap", "refused"}`. The trailing `r.event_type == "refused"` disjunct (line 276) collapses into the set-membership check. Single disjunct, not two — cleaner predicate, identical semantics on pre-v4 records, more honest on v4 records.
2. `tests/test_dashboard_model.py:267–288` — `test_confident_failure_rate_counts_high_confidence_failures` test rewritten to use `event_type='gap'` discriminators instead of `knew_answer=False`. Adds a v4-specific discriminator: a confident-and-deflected record that must NOT count.
3. `pipeline.py:204–208` writer comment — drops "slices 2 and 3 of the observability rework" framing, lands "Consumer migration complete" + v5-removal TODO.
4. `tests/test_pipeline.py:173, 264, 280` — comment refresh: drop "proxied through not knew_answer" framing.
5. `metric_status.py:56–64` — historical "demoted to orientation" framing simplified; the load-bearing caveat (denominator includes turns that don't warrant a tool call) stays.
6. `dashboard_model.technical_tool_uptake_rate` property + every reference — renamed to `technical_tool_call_rate`. Operator-facing copy on the Metrics tab + Trends tab + Sentinel runbook reframed to drop the normative "uptake" framing.

Workarounds **not** removed in slice 3, by design:

- `pipeline.py:209` — `knew_answer` writer is still in place. Removal is a future v5 schema bump.
- `interaction_log.py:51` — field declaration stays.
- Test fixture round-trips of `knew_answer=True/False` — kept; the field still exists on the schema and tests should round-trip it accurately.
- `failure_feed.py:113` module docstring footer — slice 2 added; still accurate.
- `dashboard_model.py:62` `gap_rate` comment — slice 1 added; still accurate.

---

## 7. New code surface

| File | New / edit | Purpose |
|---|---|---|
| `src/dashboard_model.py` | edit | `confident_failure_rate._failed` rewritten — `event_type in {"gap", "refused"}` disjunct. `technical_tool_uptake_rate` renamed to `technical_tool_call_rate`. `METRIC_GETTERS` registry key renamed. Docstrings on `tool_uptake_on_warranted` and `tool_call_count` updated for the rename. |
| `src/pipeline.py` | edit | Writer comment block at lines 204–208 refreshed: "Consumer migration complete" + v5 removal TODO. |
| `src/metric_status.py` | edit | Historical comment block simplified; rename references. |
| `src/sentinel.py` | edit | FRIENDLY_BANNER_LABELS, METRIC_SPECS row, METRIC_LABELS, THEMATIC_BLOCKS — every reference renamed and reframed. |
| `tests/test_dashboard_model.py` | edit | `test_confident_failure_rate_*` rewritten with `event_type` discriminators + new "deflected does not count" assertion. `test_technical_tool_uptake_rate_*` renamed and body updated. |
| `tests/test_pipeline.py` | edit | Comment refresh on the refused-turn test (lines 173, 264, 280). No assertion changes. |
| `docs/SENTINEL.md` | edit | `technical_tool_call_rate` glossary entry rewritten per § 2. Runbook header renamed. Canary-panel parenthetical rename only. |
| `docs/LIMITATIONS.md` | edit | `P8` entry — every `technical_tool_uptake_rate` mention renamed. |
| `docs/TODO.md` | edit | Slice-3 entry refreshed to reflect post-slice-3 state. |
| `CONTEXT.md` | edit (working-tree only; gitignored) | `Interaction log` entry's "only remaining reader" half-sentence rewritten. `knew_answer` legacy marking confirmed. |
| `docs/DECISIONS.md` | edit | New Session entry per the project convention — what shipped, decisions made, predicted/actual behaviour change, outstanding work + next-session entry-point. (Mirrors Sessions 44 and 45.) |

No new modules, no schema bump, no new test files. Slice 3 is structural-rewrite + rename + copy-reframing on existing files.

---

## 8. Risk register for this slice

| Risk | Mitigation |
|---|---|
| The `confident_failure_rate` rewrite is identity-preserving on the current log, so the test suite's assertion power on the migration is weak — fixtures pass on both old and new rules. | The rewritten `test_confident_failure_rate_*` test forces the new contract by including a discriminator: a confident-and-`event_type='gap'` record with `knew_answer=True` (a constructive GAP-branch response). The pre-#42 proxy would have missed it (`knew_answer=True` ⇒ not counted); the post-#42 contract counts it. Same forcing-function pattern slice 1 used on `gap_rate`. |
| Renaming `technical_tool_uptake_rate` ripples into every Trend Explorer chart spec and Metrics tab row spec. A missed reference renders the chart with no data ("metric not found" surfacing). | Audit § 5 enumerates every reference; rename is mechanical (`git grep -nE "technical_tool_uptake_rate"` → 0 hits in `src/` and `tests/` after the change). The `THEMATIC_BLOCKS["Tool use"]` registration is the load-bearing site for Trend Explorer surfacing — verified post-rename by smoke-loading Sentinel. |
| Renaming the metric in `LIMITATIONS::P8` orphans search hits for operators who Ctrl-F the old name in DECISIONS.md retrospective entries. | Acceptable. Same convention as slice 1 (`knew_answer` references in pre-#42 session entries kept as-is). The renamed metric appears in the most recent session entry; operators reading historical entries follow the trail forward via the rename note. |
| The `confident_failure_rate` band (`healthy 0.03 / warning 0.07`) was calibrated against the pre-v4 proxy and will likely read alert on healthy v4 traffic — same pattern as `gap_rate`. | Document in the slice-3 PR description and in the new `DECISIONS.md::Session 46` entry. Same operator-runbook pattern as slice 1's `gap_rate` callout: bands are descriptive-not-actionable until a week of v4 traffic accumulates and the operator sets a new healthy band. No threshold change in this slice. |
| The "deflected does not count" carve-out in `confident_failure_rate` is a semantic decision worth surfacing — a future grilling session may want confident-deflected-rate as its own metric. | Documented in § 4 with the rationale (correct out-of-scope redirect ≠ failure). If the operator wants to flag confident-deflections later, that's a new metric, not a quiet expansion of this one. PRD #41 § *Open questions* already defers similar disposition questions; same pattern applies if this surfaces. |
| `metric_status.py:56–64` simplification could lose context for a future maintainer reading the comment cold. | Keep the load-bearing sentence ("denominator includes turns that legitimately don't need a tool call"). Drop the historical narrative ("Demoted to orientation" / "previously thresholded healthy >= 0.70…"). The historical narrative is in `DECISIONS.md` for anyone who needs the trail. |
| `tool_uptake_on_warranted` (canary-side) keeps the old name through slice 3 → reads as inconsistency until slice 4 lands. | Audit § 1 calls this out explicitly. Renaming a metric in slice 3 only to delete it in slice 4 is patch-style anticipation; slice 4 owns the canary surface. |

---

## 9. Pre-flight checklist

- [ ] Test suite green pre-implementation (484 collected as of 2026-05-05; slice 2 baseline).
- [ ] After implementation, run `uv run python src/module_health.py` — no module added or removed; expected to be clean.
- [ ] After implementation, run `uv run python src/system_map.py` to refresh `docs/MAP.md` (no diagram edit needed — slice 3 doesn't add a new branch, tool, or decision point).
- [ ] After implementation, `git grep -nE "not r\\.knew_answer|not record\\.knew_answer" src/` returns **zero hits**.
- [ ] After implementation, `git grep -nE "technical_tool_uptake_rate" src/ tests/` returns **zero hits**. References in `docs/DECISIONS.md` (historical record) and `docs/LIMITATIONS.md::P8` (renamed) are the only acceptable remaining mentions; the latter should be zero too after the doc rename.
- [ ] Sentinel UI smoke-loaded post-rename: Metrics tab "Tool calls / TECHNICAL turn" row renders the value; Trend Explorer renders the renamed metric; status banner unaffected.
- [ ] PR description links back to this audit and to PRD #41.
- [ ] PR description calls out: (a) the `confident_failure_rate` migration (identity-preserving on current log, semantically more honest on v4 traffic); (b) the rename (`technical_tool_uptake_rate` → `technical_tool_call_rate`) and reframing rationale; (c) the v4-traffic forecast — like `gap_rate` after slice 1, `confident_failure_rate` will likely jump as v4 traffic accumulates and may need a threshold reset alongside it.
- [ ] `CONTEXT.md` `Interaction log` entry refreshed in the working tree (operator decides whether to stage in the slice 3 PR or hold per gitignore).

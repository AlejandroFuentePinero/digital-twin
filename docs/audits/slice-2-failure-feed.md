# Slice 2 — Failure Feed + Gap Clusters rebuild (audit)

**Issue:** [#43](https://github.com/AlejandroFuentePinero/digital-twin/issues/43)
**PRD:** [#41](https://github.com/AlejandroFuentePinero/digital-twin/issues/41) — see § *Slice 2* and § *Audit-first discipline*.
**Prior slice audit:** [`slice-1-producer-fix.md`](./slice-1-producer-fix.md) — slice 1 made `event_type` honest at the producer; slice 2 finishes the consumer migration on the Failure surfaces.
**Status:** Pre-implementation. This document lands before any code change. The PR for slice 2 includes both this audit and the implementation; reviewers verify the change matches the predictions below.

---

## 1. Scope

Slice 2 is consumer-side cleanup of two surfaces that still read the legacy `knew_answer` proxy after slice 1 left them in place by design:

- `src/failure_feed.py::classify_failure` rebuilt to read `event_type` directly. Adds a `deflected` failure mode (resolution to the deferred open question — see § 2). Drops the `knew_answer` precedence rule.
- `src/failure_feed.FAILURE_MODE_LABELS["gap"]` and the parenthetical `(knew_answer=false)` reference removed.
- `src/cluster_gaps.extract_gap_questions` keeps its current behaviour (filtering by `classify_failure(r) == "gap"`) but now picks up the v4 producer's full GAP-branch population transitively, because `classify_failure` reads `event_type` instead of `knew_answer`.
- `src/summarize_failures.select_records_for_group("deflection", …)` keeps its existing `event_type == "deflected"` predicate (already correct) — the *behaviour* change is that real records start surfacing once v4 producer traffic accumulates. The "gap" group inherits the `classify_failure` rewrite transitively.
- `src/flag_detector._REPEAT_FAILURE_EVENTS` audited and confirmed: `{"deflected", "refused"}` stays. Repeat-failure detector wiring otherwise unchanged.
- `src/sentinel.py` failure-feed accordion + per-mode summary: surfaces the new `deflected` mode and the `failure_mode` dropdown gains it.
- `docs/SENTINEL.md` runbook references to `knew_answer == False` / `(knew_answer == False OR refused)` rewritten to use the new failure-mode filters.
- Test fixtures across `tests/test_failure_feed.py`, `tests/test_cluster_gaps.py`, `tests/test_summarize_failures.py`, `tests/test_flag_detector.py`, and `tests/test_sentinel.py` switched from `knew_answer=False` proxies to direct `event_type='gap'` / `event_type='deflected'` fixtures.

`knew_answer` is **still written** by the v4 producer (slice 1 left it in for v3-record consumer compat). One read remains in `dashboard_model.confident_failure_rate` (line 274) — slice 3 finishes that consumer migration. No producer-side change in slice 2.

No new modules are introduced. No schema bump. The slice is a pure consumer-layer rewrite plus operator-facing copy alignment.

---

## 2. Resolution of the deferred open question — *should `event_type='deflected'` records appear in the failure feed?*

PRD #41 § *Intermediate-state expectations* deferred this to slice 2's audit. The decision below is binding for the implementation in this slice.

### Decision

**Yes, with a low-severity disposition.** `event_type == "deflected"` becomes a fifth `FAILURE_MODES` entry, ranked at the lowest severity tier (below `gap`), and labelled "deflected (out-of-scope redirect)" in the accordion. The default Failure Feed view *does* surface deflected rows; the per-mode summary shows the count so the operator can scan it; the severity-then-recency sort keeps deflected rows at the bottom of the feed unless explicitly filtered.

`_REPEAT_FAILURE_EVENTS` keeps `{"deflected", "refused"}` — the *repeat pattern* (3+ identical out-of-scope hits in a week) is operator-actionable; the *individual* deflected turn is correct behaviour.

### Why this resolution

Three forces drive it:

1. **The repeat-failure flag's click target is `target="failure_feed"`** (`flag_detector.py:178`). When the trip-wire fires on 3+ identical deflections of the same question in a week, the operator clicks through expecting to drill into those records. If the feed filters deflected rows out, the click-through breaks — the operator lands on a feed that doesn't contain the records the flag is pointing at. This alone forces deflected onto the failure feed *some* way.

2. **The existing taxonomy already has an "informational" tier.** `_SEVERITY_RANK` puts `gap` last with comment `# gap last (honest "I don't know" — informational, not a defect)`. Deflected slots into the same bucket: a correctly-handled out-of-scope hit isn't a defect, but seeing the pattern matters for KB / branch-design decisions. The taxonomy is built for this.

3. **The PRD's user-story #5 frames the failure feed as a *failure-shape* surface, not a *defect* surface.** Surfacing every deflected turn lets the operator see `"system deflected on this kind of question"` patterns alongside refusals and gaps. That's the use-case story #5 articulates ("see *failure shapes* not just `event_type=='refused'`").

### Why not the alternatives considered

- **Exclude deflected from the failure feed entirely.** Breaks the repeat_failure click-through. Forces a separate surface (or an in-flag inline list) just for deflected drill-downs. Adds surface, fragments the affordance, and makes the failure-mode dropdown asymmetric with the `_REPEAT_FAILURE_EVENTS` constant.
- **Hide deflected behind the dropdown filter only — don't include in the default count.** Tempting but inconsistent with how `gap` is treated (also informational, also surfaced by default). Rule of thumb: if it's surface-able, surface it; let severity rank handle the visual ordering. The operator can always set the dropdown to "All" minus deflected mentally; the layout already groups by severity.
- **Rename "failure feed" to "interaction feed" and broaden the scope.** Out of scope for slice 2 — the rename ripples through every reference in `SENTINEL.md`, `CONTEXT.md`, code comments, and tests. If the right long-term name is "interaction feed", that's a future PRD's call.

### Naming

Failure mode key: `"deflected"`. Friendly label: `"deflected (out-of-scope redirect)"`. Severity rank: 4 (below `gap`'s 3 — i.e. ranks lowest). The label is intentionally honest about the outcome ("out-of-scope redirect", not "deflection failure") so the operator's mental model stays accurate.

---

## 3. Field readers — `event_type`

Every read of `event_type` in the slice-2 surfaces today, and what slice 2 does to each.

### `src/`

| File:line | Read | Slice 2 disposition |
|---|---|---|
| `failure_feed.py:105` | `classify_failure`: `if record.event_type == "refused": return "refused"` | **Kept.** Refused stays the highest-precedence failure mode. |
| `failure_feed.py:107` | `if not record.knew_answer: return "gap"` | **Replaced** by `if record.event_type == "gap": return "gap"`. Drops the `knew_answer` proxy. |
| `failure_feed.py` (new) | — | **New branch:** `if record.event_type == "deflected": return "deflected"`. Inserted after the `gap` branch and before the retry-history branches (so retry-with-deflection still labels as `deflected`, mirroring the existing "gap takes precedence over retry" rule). |
| `failure_feed.py:40` (`FAILURE_MODES`) | `("refused", "gap", "retry-exhausted", "rejected-then-recovered")` | **Updated.** Adds `"deflected"`: `("refused", "gap", "deflected", "retry-exhausted", "rejected-then-recovered")` (ordering is informational only — `_SEVERITY_RANK` drives the actual sort). |
| `failure_feed.py:46` (`FAILURE_MODE_LABELS`) | `"gap": "unknown answer (knew_answer=false)"` | **Updated** to `"gap": "gap (couldn't answer)"`. New entry: `"deflected": "deflected (out-of-scope redirect)"`. |
| `failure_feed.py:58` (`FAILURE_MODE_SEVERITY`) | per-mode CSS class lookup | **Adds** `"deflected": "deflected"` so the per-mode count chip + accordion stripe gets a distinct class. |
| `failure_feed.py:68` (`_SEVERITY_RANK`) | `{refused:0, retry-exhausted:1, rejected-then-recovered:2, gap:3}` | **Adds** `"deflected": 4` — the lowest tier, below `gap`. Comment updated to reflect the new "informational" pair. |
| `flag_detector.py:134` (`_REPEAT_FAILURE_EVENTS`) | `{"deflected", "refused"}` | **Audited and kept.** No code change. Comment refreshed to point at the v4 producer rule rather than the writer-parity caveat. |
| `flag_detector.py:152` | `r.event_type in _REPEAT_FAILURE_EVENTS` | Unchanged code; **behaviour change:** the trip-wire starts catching real `deflected` records once v4 traffic accumulates (predicted in slice 1). |
| `cluster_gaps.py:227` | `[r.question for r in records if classify_failure(r) == "gap"]` | Unchanged code. **Behaviour change:** now picks up the v4 GAP-branch population transitively because `classify_failure` reads `event_type`. (See § 5 for the predicted clustering input growth.) |
| `summarize_failures.py:91` | `[r for r in records if classify_failure(r) == "gap"]` | Unchanged code. Same transitive change as `cluster_gaps`. |
| `summarize_failures.py:98` | `[r for r in records if r.event_type == "deflected"]` | Unchanged code. **Behaviour change:** deflection summary starts producing real Markdown content once v4 deflections accumulate. |
| `sentinel.py:1621` | `**Event:** {record.event_type}` (drilldown header) | Unchanged. |
| `sentinel.py:1666` | `record.event_type` (per-turn summary) | Unchanged. |

### `tests/`

| File | Reads `event_type` for | Slice 2 disposition |
|---|---|---|
| `test_failure_feed.py:73,76,78,102,105` | classify_failure precedence + gap-mode tests | **Updated.** Tests that passed `knew_answer=False` to assert `classify_failure(...) == "gap"` switch to passing `event_type="gap"`. The "gap takes precedence over retry" test fixture stays semantic — gap precedence is now keyed on `event_type=='gap'` not `not knew_answer`. New tests cover the `deflected` failure mode. |
| `test_failure_feed.py` (new tests) | — | **New tests:** `test_classify_failure_returns_deflected_for_deflected_event_type`, `test_classify_failure_deflected_takes_precedence_over_retry_signals` (mirrors the existing gap-precedence test), `test_select_failures_failure_mode_filter_includes_deflected`, `test_failure_mode_severity_orders_deflected_lowest`. |
| `test_cluster_gaps.py:24,35,54,61,72,80,95,250–259,302,360` | Fixtures keyed on `knew_answer=False` to simulate gap turns | **Updated.** Fixtures switch to `event_type="gap"` (with `knew_answer` either set to its v4-producer value or removed from the call site). Test docstrings updated to drop the "the canonical gap signal in live data is `knew_answer=False`" framing — the canonical signal post-#42 is `event_type='gap'`. |
| `test_summarize_failures.py:62–117, 130–170, 260–262, 329–334` | Mixed fixtures (`knew_answer=False` for gap turns; `event_type='deflected'` already direct) | **Updated.** Gap fixtures switch to `event_type='gap'`. Deflection fixtures unchanged. Docstrings refreshed where they reference `knew_answer=False` framing. |
| `test_flag_detector.py:21,32,43,57–58,67,76,101,108,137,209–280` | Mostly already on `event_type='gap'` / `event_type='deflected'` directly (slice 1 left this clean) | **Unchanged for the deflected/refused trip-wire tests.** The one fixture site reading `knew_answer=(i >= 5)` (line 137 — `gap_rate_jump` cold-start scenario) is reviewed: **kept as-is.** That test exercises the `DashboardModel.gap_rate` cold-start, and dashboard `gap_rate` is now keyed on `event_type=='gap'` (slice 1) — the fixture should mirror that. **Updated** to `event_type=("gap" if i < 5 else "answered")` in line with the `gap_rate_jump` test's intent. |
| `test_sentinel.py:48, 129–166, 218, 272, 301, 370, 506, 558, 592, 635, 662, 974` | Fixtures with `knew_answer=False` to simulate gap turns | **Updated.** All sites switch to `event_type='gap'`. Test docstrings updated where the framing is `knew_answer=False`. The `Flag(kind="repeat_failure", …)` test at line 795–796 already references "deflected 3 times in 7 days" — unchanged, but the underlying fixture for repeat_failure flag tests stays on `event_type='deflected'`. |

---

## 4. Field readers — `knew_answer`

| File:line | Read | Slice 2 disposition |
|---|---|---|
| `failure_feed.py:107` | `classify_failure`: `if not record.knew_answer: return "gap"` | **Removed** (replaced by the `event_type == "gap"` branch). |
| `failure_feed.py:48` | `FAILURE_MODE_LABELS["gap"] = "unknown answer (knew_answer=false)"` | **Updated** to `"gap (couldn't answer)"` — drops the proxy reference. |
| `dashboard_model.py:274` | `confident_failure_rate`: `not r.knew_answer` (one disjunct) | **Untouched in slice 2.** Slice 3 finishes the `knew_answer` consumer audit and removes the last read. |
| `pipeline.py:206` | Producer writer: `knew_answer = bool(last_answer) and (GAP_PHRASE not in last_answer)` | **Untouched.** v3-compat writer comment is still in place; removal scheduled for a future v5 schema bump. |
| `interaction_log.py:51` | Field declaration | **Untouched.** |
| `sentinel.py:1311` (was) | Tooltip referencing `knew_answer=False` | Slice 1 already removed this reference. **Untouched in slice 2.** |
| `tests/test_failure_feed.py:32, 56, 67, 78, 105, 115` | Fixture default + assertion | **Updated.** Default `knew_answer=True` stays as-is on the fixture builder (consumers that don't care about the field continue to ignore it); `knew_answer=False` overrides on gap-related test cases switch to `event_type="gap"`. |
| `tests/test_cluster_gaps.py` (per § 3) | Fixture sites | **Updated** per the table above. |
| `tests/test_summarize_failures.py` (per § 3) | Fixture sites | **Updated** per the table above. |
| `tests/test_flag_detector.py:23, 43, 137, 215, 278, 285` | Fixture defaults + overrides | **Updated** for the `gap_rate_jump` fixture (line 137); the `_deflected` helper's `knew_answer=False` (line 215) is a synthetic "what the producer would write for a deflected turn" — left as-is because v4 producer continues writing `knew_answer` for v3-compat. The `event_type='refused'` fixtures' `knew_answer=False` (lines 278, 285) are similarly left. |
| `tests/test_sentinel.py` (per § 3) | Many fixture sites | **Updated** per the table above. |

The audit for the *remaining* `knew_answer` reads (one in `dashboard_model.confident_failure_rate`) is slice 3's responsibility. Slice 2 stays bounded.

---

## 5. Predicted behaviour change — quantified

Computed against the local interactions log on 2026-05-05. **Live records (non-canary, n=99). All records currently on disk are pre-v4 (schema_version ∈ {1, 2}); slice 1's smart-normalize upgrades 8 of them to `event_type='gap'` at read time.**

### Today (post-slice-1, pre-slice-2)

| Metric / surface | Reading | Source |
|---|---|---|
| `dashboard_model.gap_rate` | **8.08%** (8 / 99) | `event_type == "gap"` after smart-normalize |
| `dashboard_model.deflection_rate` | **0.0%** (0 / 99) | `event_type == "deflected"`; no v4 records yet |
| `failure_feed.classify_failure(...) == "gap"` count | **8** | `not knew_answer` proxy — perfectly aligned with smart-normalized gap (because both rules key off `GAP_PHRASE in answer`) |
| `failure_feed.classify_failure(...) == "deflected"` count | n/a — branch doesn't exist | — |
| `cluster_gaps.extract_gap_questions(records, days=None)` | **8 questions** | reuses `classify_failure == "gap"` |
| `summarize_failures.select_records_for_group("deflection", …)` | **0 records** | `event_type == "deflected"`; same as `deflection_rate` |
| `flag_detector.detect_repeat_failure` over 99 records | **0 flags** | `event_type ∈ {deflected, refused}` matches 1 record (the lone refused), no repeats |

**Note on the slice-1 audit's "44.4%" predicted dashboard `gap_rate`:** that was a forecast against the *future* state where every record had been re-emitted under the v4 producer rule. Today's actual reading is 8.08% because no v4 records have been produced yet — pre-v4 records carry `event_type='answered'` for the 36 GAP-branch records that don't contain `GAP_PHRASE`. The 44% will materialise gradually as v4 traffic accumulates.

### Today (post-slice-2)

| Metric / surface | Reading | Change |
|---|---|---|
| `failure_feed.classify_failure(...) == "gap"` count | **8** | Identical to today. The two rules return the same partition over the current pre-v4 records because smart-normalize aligns them. |
| `failure_feed.classify_failure(...) == "deflected"` count | **0** | New mode with no records yet. |
| `cluster_gaps.extract_gap_questions(records, days=None)` | **8 questions** | Identical (transitively). |
| Failure Feed UI total count | **9 failures** (8 gap + 1 refused) | No `deflected` rows yet, no rejected-then-recovered or retry-exhausted rows on this log. Identical to today. |

**Slice 2 produces *zero* numerical change on the current log.** The change is structural (the contract switches to `event_type`); the visible movement only materialises as v4 traffic lands.

### Forecast — projecting v4 producer onto current records

If every current record were re-classified under the v4 producer rule (slice 1's predicted 44/7/1 distribution), slice 2 propagates that as follows:

| Surface | Pre-slice-2 reading (v4-projected) | Post-slice-2 reading (v4-projected) |
|---|---|---|
| `failure_feed.classify_failure == "gap"` count | ~8 (still keyed on `not knew_answer`; producer writes `knew_answer=True` for GAP-branch turns whose answer omits `GAP_PHRASE` — those would be missed) | **~44** (matches dashboard `gap_rate`) |
| `failure_feed.classify_failure == "deflected"` count | n/a | **~7** (matches `deflection_rate`) |
| `cluster_gaps.extract_gap_questions(records, days=None)` | ~8 questions | **~44 questions** — clustering input grows ~5×, surfacing the GAP-branch population the proxy missed |
| `summarize_failures.select_records_for_group("gap", …)` | ~8 | **~44** |
| `summarize_failures.select_records_for_group("deflection", …)` | ~7 (already correct — slice 1 unblocked this) | ~7 (unchanged) |
| `flag_detector.detect_repeat_failure` | catches refused only | **catches deflected too** (already coded that way; v4 traffic makes it meaningful) |

**Resolution of slice-1's documented intermediate-state divergence:** slice 1's audit § 5 recorded that *"dashboard `gap_rate` (~44%) and the failure-feed `gap` count (~8%) will momentarily diverge"* between slice 1 and slice 2. Slice 2 closes that gap — the failure-feed `gap` count rises to match the dashboard once both surfaces read `event_type` directly. The convergence happens *as v4 traffic accumulates*, not at slice-2 merge time (which is identity-preserving on the current log).

### What about `cluster_gaps` clustering output stability?

The clustering input grows ~5× under v4. The clustering batch (`uv run python src/cluster_gaps.py`) is operator-cadence (weekly), so the next batch run after slice 2 + the first week of v4 traffic will produce visibly more clusters or larger cluster counts. **This is the metric becoming honest, not a regression.** Documented here so the change reads as expected, and the operator's first post-#43 batch run doesn't get filed as a "clustering broke" investigation.

### What about `flag_detector.detect_new_cluster`?

`detect_new_cluster` reads from cached cluster files (current + archive). After slice 2 ships, the *next* clustering batch run will produce new cluster labels (for the v4-newly-included GAP-branch population). Some of those labels will look "new" to `detect_new_cluster` because they aren't in the archived prior runs. This is an **operator artefact** worth calling out: the first post-#43 cluster batch will likely fire `new_cluster` flags for clusters that aren't actually new — they're newly-visible.

**Mitigation for the operator:** before running the next cluster batch after slice 2 ships, archive a fresh "baseline" snapshot under `data/logs/gap_clusters_archive/` so the false `new_cluster` flags clear on the run after that. (No code change. Operator-runbook entry in `SENTINEL.md`.)

### Intermediate-state expectations between slice 2 and slice 3

- `dashboard_model.confident_failure_rate` still reads `not r.knew_answer` (line 274). For pre-v4 records that's aligned with the new world; for v4 records the disjunct will fire only on records carrying `GAP_PHRASE` (because that's when v4 producer writes `knew_answer=False`). Slice 3 finishes this consumer migration. No visible operator-facing artefact between slice 2 and slice 3 — `confident_failure_rate` remains roughly correct, just on a legacy signal.
- `pipeline.py:206` still writes `knew_answer` (v3-compat). Removal is a future v5 schema bump; not slice 3's job either.

---

## 6. Workarounds removed

Concrete list of dead-code paths and proxies that slice 2 deletes:

1. `failure_feed.classify_failure` — `if not record.knew_answer: return "gap"` replaced with `if record.event_type == "gap": return "gap"`. The `knew_answer` import is no longer needed inside this function (nothing else in `failure_feed.py` reads it after this change).
2. `failure_feed.FAILURE_MODE_LABELS["gap"]` — copy `"unknown answer (knew_answer=false)"` rewritten to `"gap (couldn't answer)"`. Drops the implementation-leaking parenthetical.
3. `failure_feed.py:45–46` — comment `"…closes the discoverability gap where an operator sees 'gap' and doesn't realise it means knew_answer=false"` deleted; the new label doesn't need the disclaimer.
4. `tests/test_failure_feed.py::test_classify_failure_returns_gap_when_knew_answer_false` — renamed to `test_classify_failure_returns_gap_for_gap_event_type` and rewritten to pass `event_type='gap'`.
5. `tests/test_failure_feed.py:67` — comment `"A turn with knew_answer=True, event_type='answered'…"` rewritten to drop the `knew_answer` part of the framing.
6. `tests/test_cluster_gaps.py::test_extract_gap_questions_keeps_records_with_knew_answer_false` — renamed and rewritten on `event_type='gap'`. Comment block at lines 54–58 (`"the canonical gap signal in live data is knew_answer=False"`) deleted; the canonical signal post-#42 is `event_type='gap'`.
7. `tests/test_summarize_failures.py:62–66` — docstring `"knew_answer=False without refused-precedence kicking in"` rewritten to `"event_type='gap' without refused-precedence kicking in"`.
8. `docs/SENTINEL.md::gap_rate jump runbook` (line 422) — `"filter to knew_answer == False"` rewritten to `"filter the failure_mode dropdown to 'gap'"`.
9. `docs/SENTINEL.md::confident_failure_rate jump runbook` (line 430) — `"(knew_answer == False OR refused)"` rewritten to `"failure_mode in {gap, refused}"` (uses the dropdown filter, not a free-text predicate).
10. `docs/SENTINEL.md::repeat_failure runbook` (line 242) — refresh: drop the slice-1-era assumption that `deflected` records won't appear and add a sentence that the failure feed surfaces deflected rows at the lowest severity tier so the click-through from the flag lands meaningfully.

Workarounds **not** removed in slice 2, by design:

- `dashboard_model.confident_failure_rate` (line 274) — still reads `not r.knew_answer`. Slice 3.
- `pipeline.py:206` — `knew_answer` is still written for v3-compat. Future v5 bump.
- `interaction_log.py:51` — `knew_answer` field declaration. Future v5 bump.

---

## 7. New code surface

| File | New / edit | Purpose |
|---|---|---|
| `src/failure_feed.py` | edit | `classify_failure` rewritten on `event_type`. `FAILURE_MODES`, `FAILURE_MODE_LABELS`, `FAILURE_MODE_SEVERITY`, `_SEVERITY_RANK` gain `deflected` entries. Module docstring footer note added: `"As of #43 the failure-mode contract reads event_type directly; knew_answer is no longer consulted."` |
| `src/flag_detector.py` | edit | `_REPEAT_FAILURE_EVENTS` comment refreshed to drop the writer-parity caveat and reference v4 producer + the slice-2 audit. No code change to the constant. |
| `src/sentinel.py` | edit | None expected. The Failure Feed UI reads `FAILURE_MODE_CHOICES` and `FAILURE_MODE_LABELS` at module load; the new `deflected` mode propagates via the dropdown automatically. CSS for the per-mode summary chip already keys on `f"feed-summary-mode {mode}"`; the new `deflected` class is styled in the existing CSS block — verify the colour palette has a distinct slot for it during implementation, add one if not. |
| `tests/test_failure_feed.py` | edit | Tests rewritten per § 3. Adds the four new tests listed in § 3. |
| `tests/test_cluster_gaps.py` | edit | Fixtures rewritten per § 3. |
| `tests/test_summarize_failures.py` | edit | Fixtures + docstrings rewritten per § 3. |
| `tests/test_flag_detector.py` | edit | Targeted fixture update at line 137 (`gap_rate_jump` cold-start fixture) per § 3. |
| `tests/test_sentinel.py` | edit | Fixture sites switched to `event_type='gap'` per § 3. |
| `docs/SENTINEL.md` | edit | Runbook references rewritten (lines 422, 430, 242). Optional addition: a one-line operator-runbook entry on the "first cluster batch after #43 may fire false `new_cluster` flags; archive a baseline snapshot first" caveat. |
| `CONTEXT.md` | edit | Glossary `Failure mode` entry refreshed to list five values (refused / gap / deflected / retry-exhausted / rejected-then-recovered) and to drop the `knew_answer=False` framing on the `gap` entry. *Note:* `CONTEXT.md` is gitignored per the operator's session-44 entry — slice 2's edits live in the working tree but are not committed; the operator can review and stage as part of the slice 2 PR if desired. |

No new module, no new test file. Slice 2 is structural-rewrite-only on existing files.

---

## 8. Risk register for this slice

| Risk | Mitigation |
|---|---|
| The `deflected` failure mode adds visual noise to the Failure Feed because the operator was previously inferring deflection from absence (deflection_rate flat 0% → "system never deflects"). | The new severity rank parks deflected rows at the bottom; the per-mode summary chip surfaces the count separately so the operator can ignore them at a glance if they're not the focus. Tooltip / glossary copy in `SENTINEL.md` will frame deflected as informational, not defective. |
| The `_REPEAT_FAILURE_EVENTS` audit kept `{"deflected", "refused"}` — a future world where deflected is reframed as fully-correct-and-unactionable would mean the trip-wire over-fires. | If that world materialises, the change is a one-line edit to the constant + a runbook update. The current read is that *repeated* deflections are operator-actionable (suggests a missing branch, a corpus pattern, or a spam category) even though *individual* deflections are correct — slice-1's audit § 5 documented this as the rationale for keeping the constant. Revisit if the first weeks of v4 traffic show the trip-wire firing on patterns that aren't actionable. |
| The first `cluster_gaps.run_batch` after slice 2 + first week of v4 traffic produces visibly more / larger clusters; reads as a regression. | Documented in § 5. SENTINEL.md operator-runbook entry calls it out. The increase is the metric becoming honest. |
| The first `cluster_gaps.run_batch` after slice 2 may fire false `new_cluster` flags because the v4 GAP-branch population contains topics that didn't surface under the proxy. | Operator-runbook entry in `SENTINEL.md`: archive a "baseline" snapshot under `gap_clusters_archive/` before the first post-#43 batch, so the next-after-that batch fires meaningfully. No code change. |
| Test fixture migrations across five test files are large; risk of a missed `knew_answer=False` site that subtly papers over the change. | The implementation order is "rewrite `classify_failure` → run the suite → fix every failing fixture site explicitly". Any site that was passing on the proxy but should be passing on `event_type` becomes a noisy fail and is fixed deliberately, not silently coerced. The `tests/test_sentinel.py:48` fixture site is the largest — covered by the central `_record` helper. |
| The `gap` failure mode label rewrite (`"unknown answer (knew_answer=false)"` → `"gap (couldn't answer)"`) breaks downstream copy that string-matches on the old label. | The label is only consumed by `sentinel.py::format_feed_summary` and `sentinel.py::_failure_accordion_label`, both of which read from `FAILURE_MODE_LABELS` at module load. No downstream string matching. Verified by grep. |
| Slice 2's structural change is identity-preserving on the current pre-v4 log, which makes the test suite's assertion power on the migration weak — fixtures pass on both old and new rules. | New tests in § 3 (`test_classify_failure_returns_deflected_for_deflected_event_type`, `test_failure_mode_severity_orders_deflected_lowest`) force the new contract. The migrated `test_classify_failure_returns_gap_for_gap_event_type` test is keyed on `event_type='gap'` directly so it can't accidentally pass on `not knew_answer`. |

---

## 9. Pre-flight checklist

- [ ] Test suite green pre-implementation (479 collected as of 2026-05-05; slice 1 baseline).
- [ ] After implementation, run `uv run python src/module_health.py` — `failure_feed.py` / `flag_detector.py` / `cluster_gaps.py` / `summarize_failures.py` all already have matching test files; no module-health change expected.
- [ ] After implementation, run `uv run python src/system_map.py` to refresh `docs/MAP.md` (no diagram edit needed — slice 2 doesn't add a new branch, tool, or decision point).
- [ ] PR description links back to this audit and to PRD #41.
- [ ] PR description calls out: (a) the `deflected` mode addition; (b) the resolution of the deferred open question; (c) the convergence of dashboard `gap_rate` and failure-feed `gap` count under the new contract; (d) the operator caveat about the first post-#43 cluster batch.
- [ ] `data/logs/gap_clusters_archive/` baseline snapshot recommendation surfaced in `SENTINEL.md` operator runbook.
- [ ] `CONTEXT.md` `Failure mode` glossary entry refreshed in the working tree (operator decides whether to stage the change in the slice 2 PR or hold per the gitignore).

# Canary three-run trajectory view (audit)

**Trigger:** Operator request — current canary tab shows latest run vs frozen baseline (one comparison snapshot). Wants the 3 runs that came after the baseline (benchmark + 1, +2, +3) shown side-by-side against the benchmark, so trajectory across recent runs is visible at a glance instead of just "this run vs last freeze."

**PRD:** Polish on the canary surface (PRD #41 slice 4 area). Same conceptual move as Sessions 48/49 — surface trajectory / shape rather than a single snapshot.

**Status:** Pre-implementation. Audit lands first; renderer reshape + helper + tests + doc updates follow.

---

## 1. The new view

Replace the (Current | Δ baseline) two-column layout in `format_canary_health_blocks` with a (Benchmark | +1 | +2 | +3) four-column trajectory layout:

```
Quality                           Benchmark | +1   | +2   | +3
Outcome accuracy                  95%       | 95%  | 92%  | 88%
Keyword coverage                  85%       | 84%  | 84%  | 78%
Red-flag rate                      0%       |  0%  |  2%  |  6%
First-attempt pass rate           94%       | 94%  | 91%  | 89%
Mean classification confidence  0.873       | 0.870| 0.851| 0.832
Tool-call success rate           100%       | 100% | 100% |  98%
```

`+1` is the first canary run that happened **after** the baseline was frozen. `+3` is the third. "Latest run" is implicit (it's whichever of `+1..+N` is the most recent — typically `+3` if at least 3 runs have happened, `+2` if only 2, etc.).

**Empty-slot handling:** when fewer than 3 post-baseline runs exist, the missing slots render as em-dash placeholders (`—`). On a freshly-frozen baseline, all three slots are empty until the operator runs `canary_runner.py` again.

**Re-baseline behaviour:** automatic. When the operator promotes a new run to baseline (via `--freeze-baseline` CLI or the Sentinel "Re-baseline" button), the new pointer's run_id becomes the baseline. `runs_after_baseline` returns whatever runs happened *after* the new pointer time — initially empty. The view degrades cleanly.

## 2. What stays unchanged

- **Drift summary banner** ("benchmark date → latest canary run date"). Stays as-is — at-a-glance flag count for the latest run vs baseline.
- **Per-question drift table.** Stays as-is — operator's actionable drilldown for the latest run.
- **Stratified summary chips** (by_outcome / by_category / by_drift_kind). Stays as-is — latest-run details.
- **Per-flag drift cards.** Stays as-is — latest-run drilldown.
- **Re-baseline button.** Stays as-is — same wiring; just operates on a richer view post-#51.
- **Drift detector itself** (`canary_drift.detect_drift`). Stays as-is — comparison is per-question, baseline-anchored. The trajectory view doesn't change drift detection; it changes how the metrics around drift are rendered.

The Drift block (Total drift flags / Major / Minor) — re-render per post-baseline run vs baseline, so the operator sees drift counts trajectory: `+1: 1 major / 2 minor`, `+2: 3 major / 4 minor`, `+3: 5 major / 6 minor`. Trend says "drift is accumulating run-over-run."

## 3. Field readers

| File:symbol | Today | Polish disposition |
|---|---|---|
| `canary_baseline.py` (new) | — | New `runs_after_baseline(records, n=3, baseline_path=...)` returning `list[str]` — the chronologically-ordered run_ids of canary runs that happened **after** the baseline pointer's `frozen_at` timestamp. Returns up to N entries (can be fewer or empty). |
| `sentinel.py::_canary_metric_row` | renders 3-column grid (label | current | Δ baseline) | **Reshaped** to render up to 5 columns (label | benchmark | +1 | +2 | +3). Grid template-columns updated; cells render em-dash when the run slot is empty. |
| `sentinel.py::_canary_section` | header row "Metric / Current / Δ baseline" | **Reshaped** header to "Metric / Benchmark / +1 / +2 / +3". |
| `sentinel.py::format_canary_health_blocks` | computes latest_model + baseline_model; renders one row per metric with current value + delta cell | **Reshaped** to compute baseline_model + 3 post-baseline run models; renders one row per metric with 4 columns. Row data computation (per-metric value lookup) refactored into a small per-row helper that takes a list of models. |
| `sentinel.py::_build_canary_drift_state` | returns `(flags, latest_records, pointer, corpus)` for the latest-vs-baseline comparison | **Extended** to also return `post_baseline_runs: list[list[InteractionRecord]]` — the records grouped per +N run. Same call sites; new field is optional / additive. |
| `sentinel.py` CSS | `.canary-row` grid — 3 columns (label / current / delta) | **Updated** to accommodate up to 5 columns. Grid template-columns: `auto repeat(4, 1fr)`. |
| `tests/test_canary_baseline.py` | tests for `freeze_baseline`/`read_baseline`/`resolve_baseline_records` | **Add** tests for `runs_after_baseline`: chronological ordering; cap at N; empty when no post-baseline runs; empty when no pointer; ignores pre-baseline runs. |
| `tests/test_sentinel.py` | smoke tests for canary tab rendering | **Add** test for the 4-column trajectory layout: 4 column headers, em-dash on empty slots, value cells per run. |

## 4. The `runs_after_baseline` helper

```python
def runs_after_baseline(
    records: list[InteractionRecord],
    n: int = 3,
    path: Path = DEFAULT_BASELINE_PATH,
) -> list[str]:
    """Return the chronologically-ordered run_ids of canary runs that
    happened after the frozen baseline. Empty when no pointer is set,
    when pointer is stale (run_id absent from records), or when no
    runs have happened since the freeze.

    Caller's responsibility: pass canary records only (`is_canary=True`
    filter applied upstream).
    """
    pointer = read_baseline(path)
    if pointer is None:
        return []
    baseline_run = pointer.get("run_id")
    frozen_at = pointer.get("frozen_at")
    if not baseline_run or not frozen_at:
        return []

    # Group records by run_id; for each run, take the earliest timestamp.
    by_run: dict[str, str] = {}
    for r in records:
        if r.run_id is None or r.run_id == baseline_run:
            continue
        first = by_run.get(r.run_id)
        if first is None or r.timestamp < first:
            by_run[r.run_id] = r.timestamp

    # Keep only runs whose earliest record is after the baseline freeze.
    post = [(ts, run) for run, ts in by_run.items() if ts > frozen_at]
    post.sort()  # chronological
    return [run for _, run in post[:n]]
```

The function is pure-data (no side effects beyond `read_baseline`'s file I/O); easily unit-testable with synthetic records.

**Why timestamp-comparison and not sequence-from-pointer:** the pointer carries `run_id` + `frozen_at`. Run_ids are time-encoded (`run-YYYYMMDD-HHMMSS-<rand6>`) but lexicographic sort would suffice IF we could trust no clock skew across runs. Using each run's earliest record timestamp + comparing against `frozen_at` is the bulletproof read — it handles operator-clock drift cleanly.

## 5. Predicted visual

**State 1 — fresh baseline frozen, no post-baseline runs yet:**
```
Quality                           Benchmark | +1 | +2 | +3
Outcome accuracy                  95%       | —  | —  | —
Keyword coverage                  85%       | —  | —  | —
Red-flag rate                      0%       | —  | —  | —
...
```

**State 2 — one post-baseline run:**
```
Quality                           Benchmark | +1   | +2 | +3
Outcome accuracy                  95%       | 94%  | —  | —
...
```

**State 3 — three post-baseline runs (the typical view after a couple of weeks):**
```
Quality                           Benchmark | +1   | +2   | +3
Outcome accuracy                  95%       | 95%  | 93%  | 91%
...
```

**State 4 — operator re-baselines from `+3` (Re-baseline button or `--freeze-baseline`):** the new pointer becomes `+3`'s run_id; trajectory resets to State 1 until the next run.

## 6. Drift block — special handling

The current Drift block shows `Total drift flags / Major / Minor` for the latest run. Under the trajectory view, each post-baseline run produces its own drift count vs the baseline. So:

```
Drift                             Benchmark | +1     | +2     | +3
Total drift flags                 —         | 3      | 7      | 11
Major drift                       —         | 1      | 3      | 5
Minor drift                       —         | 2      | 4      | 6
```

Benchmark column reads em-dash (it's the comparison anchor — drift against itself is zero by construction; rendering "0" would be misleading). Each post-baseline column carries `detect_drift(run_records, baseline_records, corpus)` re-evaluated for that run.

**Performance:** with 3 post-baseline runs × ~150 records each + drift detector re-evaluation, that's 3 × O(50 questions × per-question comparison). At canary-tab refresh time this is sub-millisecond. No caching needed.

## 7. Risk register

| Risk | Mitigation |
|---|---|
| First operator read post-#51 finds the new layout confusing — "what is +1?" | SENTINEL.md callout + tooltip on column header explaining "+N = the Nth canary run after the frozen baseline" |
| Existing helper `_delta_cell` becomes unused (today it produces the Δ baseline cell) | Keep it for the cases where deltas DO make sense in the trajectory view (e.g. summarising "+3 vs benchmark" as a footer per metric, if needed). Otherwise prune in a follow-up |
| Wide layout doesn't fit narrow viewports | Grid template-columns uses `auto repeat(4, 1fr)`; columns flex. Rendering on a narrow viewport will wrap the +N columns; not pretty but readable. Polish for a later session if it bites |
| Operator re-baselines and expects the trajectory to immediately show new runs | Documented behaviour: the trajectory resets to empty slots and fills as new runs accumulate. Banner copy notes this on first-render after a re-baseline |

## 8. Pre-flight checklist

- [ ] Suite at 522 passing pre-trajectory.
- [ ] After change, suite green; expect ~3-5 new tests (runs_after_baseline + 4-column rendering).
- [ ] Sentinel UI smoke-loaded post-change: canary tab renders cleanly with the local log's stale-pointer cold-start state (all 4 columns render em-dash; no crash).
- [ ] After Phase 5 / canary re-freeze, the operator validates the trajectory view shows real values across +N columns.

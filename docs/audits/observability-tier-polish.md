# Observability tier polish — Live tabs (audit)

**Trigger:** Session 47 Q&A revealed `confident_failure_rate=13.1%` was firing on records where ~62% were correct system behaviour (correct gap-acks on real gap questions, correct calibration-ladder answers). Post-record-by-record inspection: the metric's framing (mechanism shape labelled as failure) was the load-bearing problem, not the metric body. PRD #41 made shape metrics honest about *what* they measure; it didn't change the dashboard's structure of putting health badges on shape metrics. This audit fixes that.

**PRD:** Polish on PRD #41 / extends the user-story #1 framing ("every metric to mean exactly what its label says") to the *alerting* layer.
**Status:** Pre-implementation. Audit lands first per project discipline; code change second.

---

## 1. The three-tier framework

| Tier | Treatment | Failure semantic |
|---|---|---|
| **A — Mechanism IS failure** | Threshold on value + status badge + banner. Crossing band IS the failure event. | Refusal, retry-exhaustion, conversion drop, tool error, latency past UX bar. |
| **B — Behavioural-shift signal** | No value threshold. Shift-status against window comparisons (7d↔30d, 30d↔90d) drives the badge: relative change ≥15% = alert, ≥7% = warning. Banner collects shift-alerts alongside value-alerts. | Shape changed enough to investigate. The metric's value alone is meaningless (depends on traffic mix); the *shift* signals behavioural drift. |
| **C — Deterministic reflection** | Number only. No badges, no delta-alerts. | Pure system state — counts, distributions of identity. |
| **Useless** | Removed from dashboard. | Either semantically broken or always-zero. |

## 2. Per-metric assignment

| # | Metric | Tier | Source field |
|---|---|---|---|
| 1 | Total interactions | C | `len(records)` |
| 2 | Gap rate | B | `event_type == "gap"` |
| 3 | Deflection rate | B | `event_type == "deflected"` |
| 4 | Refusal rate | **A** | `event_type == "refused"` |
| 5 | Guardrail rejection rate | B | `any(not a["is_acceptable"] for a in attempts)` |
| 6 | Retry-exhaustion rate | **A** | `len(attempts) >= MAX_ATTEMPTS` |
| 7 | Attempts distribution | C* | `len(attempts)` bucketed (dict — render as orientation chip) |
| 8 | Classifier branch distribution | C* | `Counter(branch)` (dict — render as orientation chip) |
| 9 | Classifier mean confidence | B | `mean(classification_confidence)` |
| 10 | Classifier low-confidence rate (<0.7) | B | `classification_confidence < 0.7` |
| 11 | Classifier confident-failure rate | **Useless** | composite — **REMOVE** |
| 12 | Classifier multi-label rate | **Useless** | always 0% (composition dormant) — **REMOVE** |
| 13 | Unique sessions | C | `len(set(session_id))` |
| 14 | Avg questions per session | B | `len(records) / unique_sessions` |
| 15 | Turns/session (median) | B | `median(Counter(session_id).values())` |
| 16 | Contact-offer rate | B | `contact_offered == True` |
| 17 | Contact-conversion rate | **A** | `contact_provided` joined session-level on `contacts.jsonl` |
| 18 | Tool calls (count) | C | `sum(len(tool_calls))` |
| 19 | Tool calls / TECHNICAL turn | B | branch=='TECHNICAL' & tool_calls!=[] |
| 20 | Tool-call success rate | **A** | `tool_calls[*].status == "success"` (NEW threshold: healthy ≥0.99 / warning ≥0.95) |
| 21 | classifier (p50/p95/share) | C* | `latency_ms["classifier"]` (rendered as orientation today; diagnostic context for #25) |
| 22 | retrieval (p50/p95/share) | C* | `latency_ms["retrieval"]` |
| 23 | generation (p50/p95/share) | C* | `latency_ms["generation"]` |
| 24 | guardrail (p50/p95/share) | C* | `latency_ms["guardrail"]` |
| 25 | total (p95) | **A** | `latency_ms["total"]` p95 |

*"C*" = deterministic-by-treatment (renders as a multi-value chip / per-stage row, not a single scalar). Could earn Tier B shift-detection on individual sub-keys (per-branch-confidence, per-stage-latency) in a future iteration; current polish keeps them orientation-only to bound scope.

**Added** (not on dashboard today):

| New metric | Tier | Source field | Rationale |
|---|---|---|---|
| Mean confidence per branch | C* | `mean(classification_confidence) WHERE branch == X` per branch | Per-branch breakdown of #9; renders as a 5-row chip in the Routing block |
| Answered-with-substance rate | B | `event_type == "answered"` | Completes 4-bucket Outcome partition (gap + deflected + refused + answered = 100%) |

## 3. Shift-status spec — Tier B

```python
SHIFT_WARNING = 0.07   # 7% relative change
SHIFT_ALERT   = 0.15   # 15% relative change

def shift_status(current: float | None, prior: float | None) -> Status | None:
    """Returns 'alert' / 'warning' / 'healthy' based on relative absolute
    change. None when either input is None or prior is zero."""
    if current is None or prior is None or prior == 0:
        return None
    rel = abs(current - prior) / abs(prior)
    if rel >= SHIFT_ALERT:
        return "alert"
    if rel >= SHIFT_WARNING:
        return "warning"
    return "healthy"
```

**Per-row aggregation:** for each Tier B row the dashboard renders three windowed values [7d, 30d, 90d]. Row-level status is the worst of:
- `shift_status(v_7d, v_30d)` — recent week vs broader month
- `shift_status(v_30d, v_90d)` — recent month vs quarter

If either firing: row gets the alert/warning ribbon. Both checks short-circuit cleanly when a window is empty (returns `None` for that comparison).

**Why relative %, not absolute pp:** invariant across metric types (rates / latency / counts all behave the same). "Gap rate doubled this week" reads as 100% relative change regardless of whether absolute went 5%→10% or 30%→60%; both are equally interesting.

**Why 15% / 7%:** initial defaults. PRD #41 § *Open questions deferred* explicitly defers drift threshold tuning until first real data informs reasonable values. These bands are placeholders that can be tuned in a future grilling session after a month of operator usage shows where the noise-vs-signal line actually sits.

## 4. Field readers — Sentinel rendering

| File:symbol | Today | Polish disposition |
|---|---|---|
| `metric_status.py::THRESHOLDS` | 8 entries (incl. gap_rate, deflection_rate, etc.) | **Shrunk** to 5 Tier A entries: refusal_rate, retry_exhausted_rate, contact_conversion_rate, latency_p95_total + new tool_call_success_rate |
| `metric_status.py` (new) | — | **`TIER_B_METRICS`** frozenset; **`shift_status(cur, prior) -> Status \| None`**; **`tier_of(metric)`** helper; constants `SHIFT_WARNING=0.07`, `SHIFT_ALERT=0.15` |
| `dashboard_model.py::confident_failure_rate` | property + METRIC_GETTERS entry | **REMOVE** (property + getter + tests) |
| `dashboard_model.py::multi_label_rate` | property + METRIC_SPECS row | **REMOVE** (property + spec row + glossary entry + tests) |
| `dashboard_model.py` (new) | — | `mean_confidence_by_branch -> dict[str, float \| None]`; `answered_with_substance_rate -> float` (+ METRIC_GETTERS entries for the float metric) |
| `dashboard_model.py::METRIC_GETTERS` | 11 entries | **Modified:** drop `confident_failure_rate`; add `mean_classification_confidence`, `mean_turns_per_session`, `contact_offer_rate`, `answered_with_substance_rate`, `tool_call_success_rate` (all newly Tier-tracked) |
| `sentinel.py::METRIC_SPECS` | 5 sections × 25 rows | Drop the two useless rows; add Mean confidence per branch (Routing) + Answered-with-substance rate (Outcome) |
| `sentinel.py::METRIC_GLOSSARY` | 25 entries | Drop two; add two |
| `sentinel.py::METRIC_LABELS` | 11 entries | Drop `confident_failure_rate`; add the three new label entries for trend explorer compat |
| `sentinel.py::THEMATIC_BLOCKS` | 5 blocks | Drop `confident_failure_rate` from Routing; add `mean_classification_confidence` to Routing; add `answered_with_substance_rate` to Outcome; add `tool_call_success_rate` to Tool use |
| `sentinel.py::FRIENDLY_BANNER_LABELS` | 11 entries | Drop `confident_failure_rate`; add the new banner-friendly labels |
| `sentinel.py::_row_severity` | per-window value-status worst | **Tier-aware:** Tier A → existing per-window value status; Tier B → shift-status across window pairs; Tier C / unknown → orientation |
| `sentinel.py::_status_summary` | Iterates `THRESHOLDS` | **Iterates Tier A (value status) AND Tier B (shift status)**; both kinds of alerts surface in the banner |
| `sentinel.py::_status_class` | per-cell value status | Tier A: per-cell value status (unchanged); Tier B: per-cell colour follows row severity; Tier C: no status class |
| `metric_status.py::TIER_B_METRICS` (new) | — | `frozenset({"gap_rate", "deflection_rate", "guardrail_rejection_rate", "low_confidence_rate", "mean_classification_confidence", "mean_turns_per_session", "turns_per_session_median", "contact_offer_rate", "technical_tool_call_rate", "answered_with_substance_rate"})` |

## 5. Per-band threshold inventory after polish

```python
THRESHOLDS = {
    # Tier A only
    "refusal_rate":             Threshold(healthy=0.01, warning=0.03),
    "retry_exhausted_rate":     Threshold(healthy=0.03, warning=0.05),
    "contact_conversion_rate":  Threshold(healthy=0.10, warning=0.05, higher_is_better=True),
    "latency_p95_total":        Threshold(healthy=25_000, warning=40_000, unit="ms"),
    "tool_call_success_rate":   Threshold(healthy=0.99, warning=0.95, higher_is_better=True),  # NEW
}
```

Removed (were Tier B / Useless): `gap_rate`, `deflection_rate`, `guardrail_rejection_rate`, `low_confidence_rate`, `confident_failure_rate`, `turns_per_session_median`.

**Predicted impact on the screenshot you saw:** `Classifier confident-failure rate (≥0.8 & failed)` row — gone. `gap_rate` and similar Tier B rows — render as plain values with a delta arrow, no alert ribbon, unless the WoW shift exceeds 15% in which case the ribbon fires on the *shift*, not the value. The dashboard's "current alerts" become real failure events + meaningful behavioural shifts only.

## 6. Test surface

| File | Change |
|---|---|
| `tests/test_metric_status.py` | THRESHOLDS keyset assertion shrinks; new tests for `shift_status` (alert at ≥15%, warning at ≥7%, healthy below, None on missing inputs); new test for `tier_of` |
| `tests/test_dashboard_model.py` | Drop `test_confident_failure_rate_*` and `test_multi_label_rate_*`; add `test_mean_confidence_by_branch_*`, `test_answered_with_substance_rate_*` |
| `tests/test_sentinel.py` | Snapshot/glossary tests adapt to dropped + added rows; `_status_summary` test for combined-tier banner |

## 7. Risk register

| Risk | Mitigation |
|---|---|
| Tier B shift-alerts fire spuriously during traffic ramp-up (low N, jumps ARE 15%+ legitimately) | Existing `MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA` gate already mutes deltas under 14 days history. Apply same gate to shift-status (return None when history_days < 14). Documented in code comment |
| The 15% / 7% bands are operator-defaults, not data-grounded | PRD #41 explicitly defers threshold tuning. SENTINEL.md will note the bands are placeholders subject to recalibration after first month of usage |
| Operator misses that `confident_failure_rate` is gone (was prominent in alerts) | DECISIONS.md Session 48 + SENTINEL.md callout document the removal explicitly with rationale |
| Adding `mean_confidence_by_branch` in the Routing block adds 5 rows (one per branch) | Render as a single chip row (`GENERIC: 0.85 · GAP: 0.78 · TECHNICAL: 0.91 · ...`) — same pattern as `branch_distribution`. One row, not five |

## 8. Pre-flight checklist

- [ ] Suite at 503 passing pre-polish.
- [ ] After polish, suite green; expect ~3-4 test net delta (+5 new shift tests, -2 removed property tests, +2 new property tests, etc).
- [ ] After polish, `git grep -n "confident_failure_rate\|multi_label_rate" src/` returns zero hits.
- [ ] Sentinel canary + live tabs both render cleanly post-polish (smoke-load the app).
- [ ] PR / batch description calls out: (a) removed metrics + rationale; (b) new tier framework; (c) shift-band defaults are placeholders.

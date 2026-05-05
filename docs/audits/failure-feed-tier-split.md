# Failure Feed tier split — Failures vs Outcomes (audit)

**Trigger:** Session 49 Q&A on the Failure Feed (post-Session 48 tier polish). 3 of the 5 modes the feed surfaces (`gap`, `deflected`, `rejected-then-recovered`) aren't strict failures — they're outcome shapes labelled as failures. Same conflation Session 48 fixed for the live metric labels; the Failure Feed inherited the pre-#48 framing.

**PRD:** Polish on PRD #41, mirroring the Session 48 tier framework into the Failure Feed.
**Status:** Pre-implementation. Audit lands first; UI split + tests + doc updates follow.

---

## 1. The conflation

| Mode | Strict failure? | Reason |
|---|---|---|
| `refused` | **Yes** | System bottomed out into `CANNED_REFUSAL` after 3 rejections. No substantive answer delivered. |
| `retry-exhausted` | **Yes** | System burned its full attempt budget (`len(attempts) >= MAX_ATTEMPTS`). Includes refused AND barely-accepted attempt-3 — operator-actionable as a perf signal either way. |
| `rejected-then-recovered` | **No** | Guardrail rejected an early attempt; a later attempt was accepted. The user got a substantive answer. The guardrail did its job. |
| `gap` | **No** | Correct gap-acknowledgement on a real gap question (kdb+/q, CUDA, etc.) is the system working as designed. Same conflation Session 48 removed from `confident_failure_rate`. |
| `deflected` | **No** | Correct out-of-scope redirect. Slice 2 audit § 2 explicitly framed this as "informational, not a defect." |

**Strict failures:** 2 of 5. **Outcome shapes labelled as failures:** 3 of 5.

## 2. The split

Two sub-section headings inside the same Failure Feed panel:

- **Failures** — modes where the metric IS the failure event:
  - `refused`
  - `retry-exhausted`
- **Outcomes** — modes where the metric IS a system-output shape worth scanning for patterns:
  - `rejected-then-recovered` (guardrail intervened, recovered cleanly)
  - `gap` (system honestly said it didn't know)
  - `deflected` (system politely redirected out-of-scope)

Same data, same drilldown, same per-mode dropdown, same `repeat_failure` flag click-target. Only the visual grouping changes.

## 3. Field readers

| File:symbol | Today | Polish disposition |
|---|---|---|
| `failure_feed.py::FAILURE_MODES` | tuple of 5 modes (mutually exclusive) | **Unchanged** — still 5 mutually exclusive labels. |
| `failure_feed.py` (new) | — | New `FAILURE_MODE_TIER: dict[str, Literal["failure", "outcome"]]` mapping each mode to its sub-section. New helper `tier_for_mode(mode) -> str`. |
| `failure_feed.py::_SEVERITY_RANK` | drives sort order | **Unchanged** — within each sub-section the existing rank still orders rows. |
| `failure_feed.py::FAILURE_MODE_LABELS` | friendly per-mode strings | **Unchanged** — same labels. |
| `failure_feed.py::failure_mode_counts` | returns per-mode counts | **Unchanged** — counts already per-mode; the renderer regroups by tier. |
| `failure_feed.py::classify_failure` | per-record mode | **Unchanged** — still returns one of the 5 mode strings. |
| `failure_feed.py::select_failures` | filtered + sorted FailureRow list | **Unchanged** — same flat list; the renderer regroups for display. |
| `sentinel.py::format_feed_summary` | renders one summary row with all 5 mode counts | **Replaced** by `format_feed_summary_tiered(rows, counts)` returning two summary rows: `Failures · N total · X refused · Y retry-exhausted` and `Outcomes · M total · A rejected-then-recovered · B gap · C deflected` |
| `sentinel.py` Failure Feed accordion area | one stream of accordion cards | **Split** into two visual sub-sections each with a sub-heading + the matching subset of accordion cards. The data model (FailureRow list) stays a single stream; the renderer just partitions for display. |
| `sentinel.py` CSS | `.feed-summary` class with per-mode chip colours | **Add** `.feed-summary.failures` and `.feed-summary.outcomes` for sub-section headings; per-mode chip colours unchanged. New `.feed-section-heading` for the two sub-section labels. |
| `tests/test_failure_feed.py` | tests for classify_failure / select_failures / counts | **Add** test for `tier_for_mode` and `FAILURE_MODE_TIER` partition. |
| `tests/test_sentinel.py` | tests for format_feed_summary | **Add** test that the tiered summary renders two sub-section headings with the right per-tier counts. Existing test for `format_feed_summary` retained as a thin smoke. |

## 4. Tier mapping

```python
# failure_feed.py
FAILURE_MODE_TIER: dict[str, str] = {
    "refused":                  "failure",
    "retry-exhausted":          "failure",
    "rejected-then-recovered":  "outcome",
    "gap":                      "outcome",
    "deflected":                "outcome",
}

def tier_for_mode(mode: str) -> str:
    """Return 'failure' or 'outcome' for a mode label. Defaults to
    'outcome' on unknown — fail-soft: an unrecognised mode shouldn't
    be flagged as a strict failure."""
    return FAILURE_MODE_TIER.get(mode, "outcome")
```

## 5. What does NOT change

- The data flow. `classify_failure` still returns the same per-record mode label. `select_failures` still returns a single flat `list[FailureRow]`. `failure_mode_counts` still returns the per-mode dict.
- The `repeat_failure` flag's `target='failure_feed'` click-through. The flag fires on `event_type ∈ {deflected, refused}` repeats; one mode lives in each sub-section now, but both records still appear in the panel and the click-through still lands on real records.
- The per-mode dropdown filter. Operator can still scan / filter by mode within either sub-section.
- The session drilldown affordance ("View full session" button per row).
- Underlying CSS for per-mode chip colours. Only sub-section headings add new CSS.

## 6. Predicted visual

```
Failure Feed                                 [filter bar: branch / mode / window / search]

▾ Failures (2 total · 1 refused · 1 retry-exhausted)
  [accordion card] · refused on TECHNICAL · "How does the Digital Twin classify questions?" · 2026-05-04
  [accordion card] · retry-exhausted on GENERIC · "yes please, provide specifics" · 2026-05-04

▾ Outcomes (11 total · 5 rejected-then-recovered · 5 gap · 1 deflected)
  [accordion card] · rejected-then-recovered on ...
  [accordion card] · gap on GAP · "Have you ever worked with kdb+/q?" · 2026-05-04
  [accordion card] · deflected on LOGISTICAL · ...
```

Same accordion / drilldown UI inside each sub-section. At low N (~13 records on the local log) the split adds two sub-section headings and reorders rows — minimal visual cost. At high N the split is what makes the panel scannable: failures separated from background-noise outcome shapes.

## 7. Risk register

| Risk | Mitigation |
|---|---|
| Operator filters mode dropdown to a Failures-tier mode but no records match — empty state confusing | Per-tier "no failures match the current filters" empty state, mirroring today's flat behaviour |
| Two visual sub-sections add chrome that doesn't pay off at low N (~13 records) | Acceptable; the split's value is structural-honesty for the operator's mental model + scaling cleanly to high N. The chrome is two `<div class='feed-section-heading'>` lines — minimal |
| `repeat_failure` flag's target description in SENTINEL.md says "click-through lands on the failure feed" — operator might wonder which sub-section | Trivially: the flag fires on `event_type ∈ {deflected, refused}`; refused records land in Failures, deflected in Outcomes. SENTINEL.md updated to note both sub-sections may carry click-through targets |

## 8. Pre-flight checklist

- [ ] Suite at 515 passing pre-split.
- [ ] After split, suite green; expect ~2 net new tests.
- [ ] `git grep -n "format_feed_summary" src/` shows the renamed function only (or new `_tiered` variant alongside the deprecated single-tier renderer for backward compat).
- [ ] Sentinel UI smoke-loaded post-split: Failure Feed renders two sub-section headings with the right per-tier counts.

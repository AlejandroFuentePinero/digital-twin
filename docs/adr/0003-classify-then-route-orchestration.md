# Classify-then-route as the orchestration backbone

A monolithic system prompt that always loads `profile.md` plus all rules plus retrieved chunks puts ~6–7k tokens in every turn and degrades attention on cheaper models — a failure mode Alejandro has hit on prior projects. Instead of patching the prompt, we redesign the orchestration: a thin classifier picks a **Branch** per turn, and each branch loads only the prompt sections, retrieval depth, and tools relevant to its question type. `profile.md` is no longer injected as a single block — it is split into named sections (`identity`, `narrative_summary`, `transfer_principles`, `gap_inventory`, `logistics`, `personal_stories`) loaded selectively by branch.

## Branches and their composition

| Branch | Profile sections | Retrieval `FINAL_K` | Tools | Approx. system prompt |
|---|---|---|---|---|
| **GAP** | identity + gap_inventory + calibration_ladder | 6 | — | ~2.2k tokens |
| **BEHAVIOURAL** | identity + deflection_rule + personal_stories | 4 | — | ~1.8k |
| **TECHNICAL** | identity + transfer_principles + tool_rules | 8 | `fetch_project_readme` | ~2.9k (+ tool result if invoked) |
| **GENERIC** | identity + narrative_summary + transfer_principles | 6 | — | ~2.9k |
| **LOGISTICAL** | identity + logistics_block | 2 | — | ~1.0k |

A cheap classifier (`gpt-4.1-nano`) takes the last 2 turns of history plus the current question and returns `{labels: list[str], confidence: float}`. High confidence + single label → that branch. Multi-label (max 2) → composition takes the union of needed sections. Low confidence → defaults to GENERIC. Misclassifications are logged with the confidence score so the **Sentinel** can flag persistent low-confidence patterns.

The same composed-from-constants pattern applies to the **Guardrail**: branch-specific rules live in shared constants imported by both `answer.py` and `guardrail.py` so calibration-ladder / deflection rules cannot drift between generator and judge.

## Considered alternatives

- **Monolithic always-on prompt** (the original ADR-0001 design). Rejected: 6–7k-token prompt diluted attention on `gpt-4.1`-class models; cognitive overload was a known failure mode from prior work.
- **Section trimming inside the monolithic prompt.** Rejected: a band-aid, not a structural fix. Eventually hits the same wall as the system grows.
- **Tool-loaded context (model decides what to fetch via tools).** Rejected for v1: cheap models are unreliable at tool selection; routing gives deterministic context loading with the option to layer tool autonomy inside specific branches (TECHNICAL).

## Consequences

- ADR-0001's "always-on injection" claim is **superseded**. `profile.md` is still the single source of frame content, but now structured as named sections rather than injected whole.
- `answer.py` is rewritten as: classifier → branch dispatch → branch-specific generator → guardrail. The current monolithic `answer_with_guardrail` is replaced.
- `guardrail.py` is rewritten branch-aware. Shared rule constants prevent drift.
- New modules: `classifier.py`, branch composers (one module or one file with named functions per branch).
- Per-turn latency adds ~200–400ms for the classifier call. Bounded; validated post-deployment via Sentinel.
- Tests for `answer.py` and `guardrail.py` are largely thrown out and rebuilt for the routed pipeline. `ingest.py` and `eval/run_eval.py` are unaffected.
- The `Interaction log` schema gains `branch`, `classification_confidence`, and `tool_calls` fields. Sentinel uses these for failure-mode analysis.
- Topic switches mid-session are handled by per-turn re-classification; conversation history flows through unchanged.

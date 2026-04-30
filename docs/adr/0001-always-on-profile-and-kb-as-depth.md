# Always-on profile + KB-as-depth

> **Status:** partially superseded by [ADR-0003](./0003-classify-then-route-orchestration.md). The Frame/Substance split, the existence of `profile.md`, and the discipline that profile content does not duplicate KB content remain. The "single block, always-on injected" mechanism is replaced by per-branch loading of named profile sections.


The Digital Twin needs to reason holistically about questions that retrieval alone cannot serve well — gap questions ("do you have AWS?"), generic recruiter questions ("why hire you?"), and behavioural questions whose answers must reference the whole career arc, not one chunk. We split the agent's knowledge into a **Frame** (always-on) and **Substance** (retrieved). The Frame is a single purpose-built file `data/profile.md` (~2,000–2,500 tokens) injected into every system prompt: identity, narrative summary, transfer principles, gap inventory. The Substance is the existing knowledge base, fetched on demand. `SUMMARY.md` and `positioning.md` are kept in retrieval but pruned of overlap with `profile.md` — `profile.md` carries narrative patterns, `SUMMARY.md` keeps granular counts and tables, `positioning.md` keeps the parallels table and worked examples.

## Considered alternatives

- **Reuse `SUMMARY.md` + `positioning.md` directly as the always-on context.** Rejected: those files were written for retrieval, not for always-on injection — too verbose and structured for table-style holistic queries rather than narrative reasoning.
- **Remove `SUMMARY.md` from the KB once `profile.md` exists.** Rejected: the two serve different purposes. `profile.md` is the narrative frame for reasoning; `SUMMARY.md` is the tabular detail surfaced by retrieval for explicitly-numerical or holistic queries. Removing `SUMMARY.md` would lose granular detail in the depth path.
- **Rely on retrieval alone, with no always-on context.** Rejected: retrieval can miss, and the failure mode for gap questions is silence or fabrication rather than the gap-aware response we want. The Frame must be guaranteed present.

## Consequences

- `profile.md` is the new always-on file; injected before retrieved chunks in every system prompt.
- `SUMMARY.md` and `positioning.md` are kept in retrieval but rewritten to remove narrative content that moves into `profile.md`. They retain their tabular-detail / parallels-table specialism.
- The gap inventory lives directly inside `profile.md`, not as a separate `gaps.md` file.
- Per-turn input tokens grow by ~2,000–2,500 (acceptable at portfolio traffic).
- `profile.md` is iterated based on unacceptable answers — it is the highest-leverage tuning surface in the system.
- Drift risk between `profile.md` and `SUMMARY.md` is mitigated by *content separation*, not synchronisation: `profile.md` does not contain numbers that exist in `SUMMARY.md`; it summarises patterns. `SUMMARY.md` keeps the numbers.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Python 3.12, managed with `uv`. All commands use `uv run` — no venv activation needed.

```bash
uv sync                  # install/update dependencies
```

Environment variables live in `.env` at the repo root (loaded via `python-dotenv`). Required keys: `OPENAI_API_KEY`. The `.env` file is gitignored.

## Project: Digital Twin

A conversational agent representing Alejandro de la Fuente professionally — answering recruiter and professional questions about skills, experience, research, and projects.

**The architecture was redesigned on 2026-04-29.** Canonical sources:

- **Glossary:** [`CONTEXT.md`](./CONTEXT.md) — every domain term used in this project.
- **Architectural decisions:** [`docs/adr/`](./docs/adr/) — three ADRs covering the Frame/Substance split (0001), HF Dataset as canonical log store (0002), and classify-then-route orchestration (0003).
- **Active phase plan:** [`docs/TODO.md`](./docs/TODO.md) — current 7-phase rebuild.
- **Project history:** [`docs/DECISIONS.md`](./docs/DECISIONS.md) — session-by-session log including the redesign (Session 12).
- **Testing convention:** [`docs/TESTING.md`](./docs/TESTING.md) — matching `test_<module>.py` rule, mock-at-boundary policy, no-LLM-API-calls in tests, exemption list. Run the local module-health dashboard with `uv run python src/module_health.py`.
- **System map:** [`docs/MAP.md`](./docs/MAP.md) — top section is the hand-edited runtime pipeline diagram ([`docs/pipeline_diagram.mmd`](./docs/pipeline_diagram.mmd)); below it the auto-generated module graph + glossary. Refresh both with `uv run python src/system_map.py` after touching modules in `src/` *or* after editing the pipeline diagram. Update the .mmd file whenever runtime behaviour changes (new branch, new tool, new decision point, retry policy change, new log field).
- **Limitations register:** [`docs/LIMITATIONS.md`](./docs/LIMITATIONS.md) — living register of observed and predicted system-wide limitations and operational risks, with explicit trip-wire conditions per entry. Read this when interpreting smoke-test results or planning new branches; update after every smoke-test round, ADR change, or production incident. Companion to ADR-0003's Operational risks section.

### Architecture summary (post-redesign)

```
User query
    │
    ▼
Classifier (gpt-4.1-nano)
    │  picks Branch: GAP | BEHAVIOURAL | TECHNICAL | GENERIC | LOGISTICAL
    ▼
Branch composer
    │  loads named profile.md sections + branch rules + retrieved chunks
    ▼
Generator (gpt-4.1)  ──► [TECHNICAL only: tool loop with fetch_project_readme]
    │
    ▼
Guardrail (Claude Sonnet 4.6, branch-aware rules)
    │  retry loop with structured feedback (max 3 attempts)
    ▼
Enriched interaction log  ──►  HuggingFace Dataset (prod) / local JSONL (dev)
                                    │
                                    ▼
                              Sentinel (local Gradio app, on-demand)
```

**Key structural facts:**
- `profile.md` (~2–2.5k tokens) is the always-on **Frame** — sectioned by named `##` blocks loaded selectively per branch. Lives at `data/profile.md`, outside the KB folder, never ingested.
- `data/knowledge_base/` is the **Substance** — retrieved on demand, one ChromaDB collection.
- `data/readmes/` is **tool-only content** — 24 distilled project / paper docs the TECHNICAL branch can fetch via `fetch_project_readme`. Outside `data/knowledge_base/`, never ingested. Registry at `data/readmes/registry.json` (24 keys; ToolRegistry hard-fails at startup if any referenced file is missing).
- `data/canaries/` is **drift-detection content** (#39) — `corpus.json` (50 curated probe questions) + `baseline.json` (frozen golden run pointer). Replayed via `uv run python src/canary_runner.py` at operator cadence; not auto-refreshed.
- One enriched interaction log (schema v4 — `is_canary` / `run_id` / `replicate_index` added in #39 at v3, `event_type` upgraded to four values in #42 at v4) replaces the three-file plan in the original PLAN.md. Schema at `interaction_log.InteractionRecord`. Live and canary records share `data/logs/interactions.jsonl`; the `is_canary` flag is the only discriminator. `DashboardModel` filters canary records out by default so live tabs are unaffected. Read-time migration in `schema_migrations.py` (slice C / `#48`) keeps the dashboard insulated from future bumps.
- `fetch_project_readme` is the only model-callable tool; available only in the TECHNICAL branch.
- Per-session **contact-flow** (#16) runs as a side-channel: `SessionState` (in `gr.State`) tracks turn count + contact-provided latch; collapsible contact form appears at turn 3; on submit, writes `ContactRecord` to `data/logs/contacts.jsonl` joinable to `interactions.jsonl` on `session_id`. App-level concern, separate from the per-turn pipeline.
- **Canary side-channel** (#39) runs as a CLI batch: `canary_runner.py` replays the corpus N=3 times per question through the same `Pipeline.run()` live turns use. The runner wraps `LogWriter` in a `_CanaryLogWriter` that injects `is_canary=True` + shared `run_id` + per-replicate `replicate_index`. Records land in the canonical log; the Sentinel Canary tab reads them via `DashboardModel(records, include_canary=True, only_canary=True)`. Manual-only — not auto-refreshed on Sentinel launch.

### Running the example implementation

The `example/rag-example/` directory contains a reference implementation (branded "Insurellm", from a course). It pre-dates the redesign and is kept only as a historical reference — do **not** treat it as the template for the rebuild.

### Evaluation (`eval/tests.jsonl`, 149 Q&A pairs)

- 7 categories: `direct_fact`, `temporal`, `comparative`, `numerical`, `relationship`, `spanning`, `holistic`
- Retrieval metrics: MRR, nDCG, keyword coverage
- Answer metrics: LLM-as-judge on accuracy, completeness, relevance (1–5 scale)
- Targets: MRR/nDCG > 0.75, accuracy/appropriateness > 4.0/5
- v3 baseline (pre-redesign): MRR 0.868, accuracy 4.46, gap rate 0.7%
- v4+ measure the routed system; the v3 → v4 comparison has caveats (routing reshapes retrieval).

## Issue tracking

Issues live in GitHub Issues at [`AlejandroFuentePinero/digital-twin`](https://github.com/AlejandroFuentePinero/digital-twin/issues). Default label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.

## Domain docs

Single-context — one [`CONTEXT.md`](./CONTEXT.md) + [`docs/adr/`](./docs/adr/) at the repo root.

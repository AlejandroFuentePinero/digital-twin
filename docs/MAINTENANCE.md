# Digital Twin — Maintenance

**Status:** Phase 7 closed at Session 63 (2026-05-07). System is deployed at <https://alejandrofupi-digital-twin.hf.space>, embedded on the portfolio home page, instrumented. **Observe-mode** is the posture — no active engineering work scheduled, only reactive iteration on real-recruiter signal.

This file is the entry point when re-engaging. Read this before opening any other doc.

---

## Periodic checks

### Monthly

- [ ] **Run the canary** as a `+N` trajectory point against the current frozen baseline. Triage drift; classify as expected variance vs new signal.
  ```bash
  uv run python src/canary_runner.py --replicates 3
  ```
- [ ] **Open Sentinel against production logs.** Review:
  - **Flags panel** — any new `gap_rate_jump`, `new_cluster`, `repeat_failure` flags fired this month?
  - **Failure Feed** — scan recent `event_type=refused` + `event_type=deflected` sessions; spot any patterns (same question shape recurring, contact-form ask going unsubmitted).
  - **Writer-health panel** — `last_flush_time` recent, `last_error` blank, `buffer_size` bounded.
  - **Trends tab** — gap rate / deflection rate / latency stable WoW.
  ```bash
  uv run python src/sentinel.py
  ```
- [ ] **Check contact submissions** — any new entries in `Alejandrofupi/digital-twin-logs/contacts/*.jsonl`. Cross-reference against email; respond to any pending ones.

### Quarterly

- [ ] **Run the full eval** (retrieval + answer) against the current pipeline. Compare to v4 baseline (MRR 0.866, accuracy 4.56). Major regression → investigate. The `run_id` is auto-derived (`v<N>_<YYYY-MM-DD>`); pass `--notes` to record the trigger.
  ```bash
  uv run python eval/run_eval.py --notes "Quarterly maintenance run"
  ```
- [ ] **Audit content for stale tense / dates** — walk `data/profile.md` + `data/knowledge_base/*.md` for "currently" / "present" / "now" references that no longer match reality (role changes, completed courses, new projects).
- [ ] **Audit canary corpus for KB drift** — if KB rewrites changed >20% of section content since the last audit, walk `data/canaries/corpus.json` line-by-line; replace questions whose grounding was removed; add questions for new flagship content. (`LIMITATIONS::P13`.)
- [ ] **Review watch-items against accumulated traffic** — see `docs/LIMITATIONS.md`. Specifically `P8` (initial-drill tool firing) and `O8` (guardrail cross-branch evaluation gap). If trip-wire conditions met, convert to fix-candidate; otherwise leave dormant for another quarter.

### Annually

- [ ] **Re-baseline canary if appropriate** — explicit operator decision, not automatic. The current baseline (`run-20260505-132248-4aeb15`, frozen 2026-05-05) accumulates trajectory points over time; re-baseline when intentional architectural changes ship and the pre-change anchor stops being informative. See `feedback_canary_baseline_freeze_is_explicit.md`.
  ```bash
  uv run python src/canary_runner.py --replicates 3 --freeze-baseline
  ```
- [ ] **Tier B band tuning** — recalibrate the 7%/15% confidence band placeholders against accumulated production data. Logged in TODO.md.
- [ ] **Renew API keys** — OpenAI, Anthropic, HF tokens. Update `.env` locally + Space secrets in HF UI.

---

## On-demand checks

### After a content change (KB / `profile.md` / `data/readmes/*.md`)

1. Re-ingest:
   ```bash
   uv run python src/ingest.py
   ```
2. Sanity-check retrieval on a relevant probe:
   ```bash
   uv run python -c "
   import sys; sys.path.insert(0, 'src')
   from retrieval import fetch_context
   for h in fetch_context('your probe question here', history=[])[:3]:
       print(f\"  {h.metadata.get('source_file')} :: {h.metadata.get('section_heading','')[:80]}\")
   "
   ```
3. Run canary as a `+N` trajectory point (don't freeze unless you're explicitly retiring the old baseline).
4. Redeploy Space (see [`deployment-runbook.md`](./deployment-runbook.md)).
5. Verify the deployed Space — open the URL, ask a question that should hit the new content, confirm it's served.

### After a code change to the pipeline (classifier / composer / generator / guardrail / pipeline)

1. Run the suite:
   ```bash
   uv run pytest -q
   ```
2. Run canary as a `+N` trajectory point — pipeline changes are exactly what canary trajectory is for.
3. Redeploy Space.
4. Smoke-test live: one question per branch (GENERIC / GAP / TECHNICAL / BEHAVIOURAL / LOGISTICAL).

### After a provider outage / Space restart

1. Open Sentinel; check writer-health panel (`last_error` should clear within minutes of recovery).
2. Check `contacts/*.jsonl` and `logs/*.jsonl` for the day — confirm records are landing again.
3. If the buffer file `data/logs/.hf_buffer.jsonl` exists locally, the writer's crash-recovery path will flush on next start; verify it did via the writer-state file.

### Recruiter feedback inbound

1. Log it (DECISIONS.md or a follow-up issue).
2. Assess against `LIMITATIONS.md` — does the feedback match a documented watch-item? If yes, increment its "observed instances" count.
3. If a fix is warranted: open a GitHub issue, label `needs-triage`, link to the feedback context.

---

## Trip-wires (when these fire, take action)

| Trip-wire | Source | Action |
|---|---|---|
| 5+ initial-drill failures in a month (recruiter asks named project, gets gap-acknowledged instead of tool-fetched README) | `LIMITATIONS::P8` | Fix-candidate or formal accept |
| 5+ cross-branch guardrail mis-flags | `LIMITATIONS::O8` | Fix-candidate or formal accept |
| Confident-failure rate jumps >5pp WoW on Sentinel | `flag_detector::detect_gap_rate_jump` | Investigate via Failure Feed |
| New gap cluster appears in cluster_gaps weekly batch | `flag_detector::detect_new_cluster` | Read cluster summary, decide content update |
| Same question repeats with refused→answered shape | `flag_detector::detect_repeat_failure` | Open Failure Feed session view, identify what changed |
| Canary drift: any major flag on a question that wasn't drifting last run | Sentinel Canary tab | Triage per Session 55 / 62 partition pattern |
| API key expiring in <14 days | Manual reminder | Rotate in `.env` + Space secrets |

---

## Quick reference commands

```bash
# === Local dev / inspection ===
uv sync                                        # install deps
uv run pytest -q                               # run suite
uv run python src/ingest.py                    # re-ingest KB
uv run python src/sentinel.py --local          # Sentinel against local JSONL only
uv run python src/sentinel.py                  # Sentinel against prod (HF env required)
uv run python src/canary_runner.py --replicates 3                     # +N trajectory run
uv run python src/canary_runner.py --replicates 3 --freeze-baseline   # promote latest run to baseline (operator decision)
uv run python eval/run_eval.py --tag <tag>     # full eval

# === Deploy ===
uv run python scripts/deploy_to_space.py       # uploads working tree to the Space
# If preprocessed_db gets filtered by .gitignore, follow with the targeted upload
# from docs/deployment-runbook.md.
```

---

## Pending follow-ups (logged, not scheduled)

These are observation-driven — they convert to active work only if observe-mode signal justifies them.

- **Drop fuzzy off-topic canary questions** ("favourite colour", "breakfast") that have no defensible correct branch.
- **Tighten `branch_changed` to unanimous-vote** (3/3 required across replicates) to stop single-record flips swinging majorities.
- **Per-question canary stability scoring** — downweight chronically-unstable questions in the drift count.
- **v6 eval against the deployed pipeline** — only if real-recruiter traffic surfaces an answer-quality regression worth measuring.
- **Pin `requirements.txt` to exact `uv.lock` versions** — only if a future redeploy surfaces version-drift symptoms; current cached install is the smoke-tested set.

---

## Reference docs

- [`docs/LIMITATIONS.md`](./LIMITATIONS.md) — watch-items + trip-wires + observed failure modes.
- [`docs/SENTINEL.md`](./SENTINEL.md) — dashboard usage guide, metric definitions, canary tab.
- [`docs/DECISIONS.md`](./DECISIONS.md) — session-by-session log; historical context for any decision.
- [`docs/deployment-runbook.md`](./deployment-runbook.md) — redeploy + rollback procedures.
- [`docs/TESTING.md`](./TESTING.md) — testing conventions + exemption list.
- [`docs/TODO.md`](./TODO.md) — phase-level history (Phases 1–7, now closed).
- [`docs/adr/`](./adr/) — architectural decision records.
- [`CONTEXT.md`](../CONTEXT.md) — domain glossary.

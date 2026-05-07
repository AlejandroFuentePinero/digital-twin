# Deployment runbook — HuggingFace Spaces

How to deploy the digital twin to its production Space and how to roll back when something goes wrong. Phase 7 / slice 1 (`#51`) artefact.

The Space is the **standalone** delivery surface — public on `*.hf.space`. Slice 2 (`#52`) embeds it as an iframe on the portfolio home page; that workflow has its own runbook on the portfolio repo.

---

## Pre-deploy checklist

Before pushing to the Space remote:

- [ ] All Phase 1–6 work merged into `main` (issues `#1`–`#5` closed).
- [ ] Local `uv run pytest` passes (`623+ passing, 1 skipped`).
- [ ] `data/preprocessed_db/` exists and is up-to-date — re-run `uv run python src/ingest.py` if the KB has changed since last ingest.
- [ ] `.env` carries `OPENAI_API_KEY` + `ANTHROPIC_API_KEY` + `HF_TOKEN` (write scope on `Alejandrofupi/digital-twin-logs`).
- [ ] `data/profile.md` reads as Alejandro would write it — production traffic sees this verbatim.
- [ ] `README.md` frontmatter at the top of the file (between `---` fences) lists `sdk_version` matching a real Gradio release.

---

## One-time setup

The Space and the dataset both live under the `Alejandrofupi` namespace.

1. **Create the Space** in the HuggingFace UI:
   - Go to <https://huggingface.co/new-space>.
   - Owner: `Alejandrofupi`. Space name: `digital-twin`. Public visibility (the chat is meant to be tried by recruiters).
   - SDK: **Gradio**. Hardware: **CPU basic** (free). The pipeline is I/O-bound on LLM calls; CPU is sufficient.
   - License: **MIT**.
2. **Configure secrets** (Space → Settings → Variables and secrets):
   - `OPENAI_API_KEY` — for `gpt-4.1` (generator), `gpt-4.1-nano` (classifier, event classifier), `text-embedding-3-small` (retrieval).
   - `ANTHROPIC_API_KEY` — for `claude-sonnet-4-6` (guardrail).
   - `HF_TOKEN` — write token for `Alejandrofupi/digital-twin-logs`.
   - `HF_DATASET_REPO` — `Alejandrofupi/digital-twin-logs`.
   - `DIGITAL_TWIN_LOG_BACKEND` — `hf`.
   All five are required. With `DIGITAL_TWIN_LOG_BACKEND=hf` set and `HF_DATASET_REPO` missing, the Space will fail at startup (`make_log_writer` raises `RuntimeError`). With `HF_TOKEN` missing, writes will fail silently and `hf_writer_state.json` will surface the error in Sentinel.
3. **Add the Space remote** to the local repo (one-time):
   ```bash
   git remote add space https://huggingface.co/spaces/Alejandrofupi/digital-twin
   ```

---

## Deploy

Production deploys go through a temporary `space-deploy` branch so the GitHub `main` history stays clean. The branch force-adds `data/preprocessed_db/` (gitignored on `main` because it's regenerable + 23 MB of binary) so the Space gets the vector store immediately at first launch.

```bash
# From a clean main (no uncommitted changes)
git checkout -b space-deploy

# Force-add the gitignored vector store; it's needed for retrieval at runtime.
git add -f data/preprocessed_db/
git commit -m "Deploy: include vector store"

# Push the deploy branch as the Space's main.
git push space space-deploy:main --force

# Return to main and discard the deploy branch.
git checkout main
git branch -D space-deploy
```

**Why `--force`:** every deploy rewrites the Space's `main`. The Space's git history is intentionally throwaway — it carries the deploy snapshot, not the design history. The canonical history is on GitHub.

**Alternative (not recommended for first deploy):** drop the force-add step and run `python src/ingest.py` as part of the Space's startup. Adds ~30 s + a few cents of embedding cost to every cold start; only worthwhile if the KB churns more than weekly.

---

## Verify the build

After `git push space …` returns:

1. Open <https://huggingface.co/spaces/Alejandrofupi/digital-twin> in a browser. The build log streams live in the **App** tab → **logs**.
2. Watch for:
   - `pip install` resolves cleanly against `requirements.txt`.
   - The Gradio launch line (`Running on local URL: http://0.0.0.0:7860`).
   - **No** Python tracebacks. The most likely failure modes are:
     - `RuntimeError: ToolRegistry: missing readme file …` — registry vs disk drift; check `data/readmes/registry.json`.
     - `RuntimeError: DIGITAL_TWIN_LOG_BACKEND=hf requires HF_DATASET_REPO env var` — secret missing; fix in Settings.
     - `chromadb` errors on the first query — the deploy commit didn't include `data/preprocessed_db/`; redeploy with the force-add step.
3. Once the green **Running** badge shows, copy the Space URL — it's the input to the smoke test below.

---

## Smoke test (11 steps, against the live Space)

Run these in one fresh browser session against the standalone Space URL. Capture timing for steps 1 and 2.

| # | Step | Expected |
|---|---|---|
| 1 | Open Space in a fresh tab. **Time the cold start** (wall-clock from URL submit to chat input visible). | < 30 s on free tier; record the actual number. |
| 2 | Send `Why hire Alejandro?` (GENERIC). **Time turn-1 latency.** | Coherent narrative answer; no fabrication. Record p50 baseline. |
| 3 | Send `Do you have AWS experience?` (GAP). | Gap-aware response: named platforms (GCP / on-prem) + active learning + acknowledgement. |
| 4 | Send `How does the chunking work in the Expert Knowledge Worker project?` (TECHNICAL). | Tool fires (`fetch_project_readme` visible in Sentinel); answer carries depth from the README. |
| 5 | Send `Tell me about a time you failed.` (BEHAVIOURAL). | Graceful deflection or a `personal_stories` story; not a generic AI-sounding answer. |
| 6 | Send `What's your salary expectation?` (LOGISTICAL). | Polite redirect to email contact. |
| 7 | Look at the page after turn 3. | Contact form Accordion appears under the chat with the initial invitation copy ("Want a follow-up?"). |
| 8 | Submit the contact form (test name + email + note). | Form swaps for the success message ("Thanks — Alejandro will be in touch."). **First production write to the contacts/ path** — see "Watch-item" below. |
| 9 | Click **New conversation**. | Chat clears, contact form hides, contact-status hides, form input fields clear, fresh session_id. |
| 10 | Run Sentinel locally with prod creds: `HF_TOKEN=… HF_DATASET_REPO=Alejandrofupi/digital-twin-logs uv run python src/sentinel.py` | All 9 turns from the smoke test appear in the Failures / Trends tabs; the contact submission joins to its session via `contact_conversion_rate`. |
| 11 | Inspect the Sentinel "Log writer health" panel (Metrics tab). | `last_flush_time` is within the last few minutes of the smoke test; `last_error` is blank. |

Steps to capture in the close-out write-up: cold-start latency (step 1), turn-1 latency (step 2), p50 across turns 2–6, p95 across turns 2–6.

**Watch-item — first production contact-path write (step 8).** Slice E (`#50`) shipped the HF contact-writer with unit-test coverage only; this is its first end-to-end production exercise. If the form submission appears to succeed (UI swaps to success message) but the record never shows up in `contacts/YYYY-MM-DD.jsonl`, suspect the buffer path / atexit registration in `make_contact_writer`. Diagnose with `huggingface-cli download Alejandrofupi/digital-twin-logs --repo-type dataset --include "contacts/*.jsonl"`.

---

## Optional — v6 eval against the deployed pipeline

Story 13 from the parent PRD (`#6`). Skip on first deploy unless the smoke test surfaces an answer-quality regression. Mark **deferred** in the close-out otherwise.

If running:

```bash
uv run python eval/run_eval.py --tag v6 --notes "Run against deployed Space via in-process pipeline; deployment marker."
```

(The eval is in-process — it doesn't actually hit the Space's HTTP endpoint. The "v6" tag is the deployment marker on the result file.)

---

## Rollback

The Space's git history is a series of deploy snapshots. Reverting is one git push:

```bash
# Find the Space commit you want to roll back to.
git fetch space
git log space/main --oneline | head -10

# Force-push that commit as the new main. Replace <sha> with the target.
git push space <sha>:main --force
```

The HF Spaces UI also exposes a "factory rebuild" button on the Space page (Settings → Factory rebuild) which clears the build cache without a code change — use this when the symptom is "build cache is wedged" rather than "the latest commit is broken."

If the breakage is confined to secrets misconfiguration, rolling back the Space code won't help — fix the secret in Settings → Variables and secrets, then trigger a rebuild from the Space's UI.

---

## Updating the deployed Space (post-launch)

The Space is recreated end-to-end on every deploy via the `space-deploy` branch flow above. There is no separate "patch" path; small fixes and major version bumps both go through the same force-push.

For pure config changes (a typo in a profile section, a tweak to a starter prompt), the deploy turnaround is on the order of 1–2 minutes from `git push` to live. For dependency bumps, expect closer to 4–5 minutes (full pip resolve + container rebuild).

---

## Limits + known sharp edges

- **Free tier sleeps** after ~48 h of inactivity. Cold starts impose the latency from step 1 of the smoke test on the first visitor of the day. Decision (parent PRD): one month of Sentinel data tells whether to upgrade.
- **`data/logs/.hf_buffer.jsonl` lives on the Space's ephemeral filesystem.** A crash-recovery flush on container restart catches anything left buffered (slice B, `#47`); a hard kernel kill could in theory lose a few unflushed records. Acceptable for portfolio scope.
- **Secrets are not in git.** They live only in HF Spaces Settings. Do not commit them; do not echo them in build logs.

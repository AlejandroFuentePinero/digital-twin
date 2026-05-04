# Release / End-of-project checklist

Pre-deploy verification that every artifact reflects the deployed system. Run through this before declaring the project finished or shipping a major release. Tick items only after physical verification — not from memory.

## Documentation freshness

- [ ] `docs/MAP.md` and `docs/MAP.html` regenerated against current `src/` (`uv run python src/system_map.py`). Inspect the output: every module appears, no stale `Legacy` cluster unless intentional.
- [ ] `docs/pipeline_diagram.mmd` reflects current runtime behaviour: every branch in `branches.REGISTRY` is shown, every model-callable tool is shown solid (not dashed), every retry/decision point matches `pipeline.py`, every log field on the `LOG` node matches `interaction_log.InteractionRecord`.
- [ ] `docs/DECISIONS.md` has a final session entry summarising the deployed state (commits, test count, KB chunks, branches live, open issues left, known limitations).
- [ ] `docs/TODO.md` is at final state — completed phases marked, open items either ticketed or deliberately deferred with a note.
- [ ] `docs/HUMAN_EVAL_QUESTIONS.md` carries probes for every wired branch (GAP, BEHAVIOURAL, TECHNICAL, LOGISTICAL, GENERIC) including adversarial pressure for each.
- [ ] `docs/LIMITATIONS.md` (issue #20) is current — observed misclassification patterns, retrieval failure modes, scope limits, deferred work documented from observation, not prediction.
- [ ] Every architectural decision made post-redesign has an ADR in `docs/adr/` or is captured in an existing ADR's "Operational risks" section.
- [ ] `CONTEXT.md` glossary covers every domain term used in code and docs. No new term in the codebase that doesn't appear here.
- [ ] `CLAUDE.md` Architecture Summary section matches the deployed flow.
- [ ] Pre-redesign artifacts (`docs/PLAN.md`, `docs/ARCHITECTURE.md`) either updated or explicitly marked as historical record.

## Code / test integrity

- [ ] `uv run pytest -q` — all tests pass.
- [ ] `uv run python src/module_health.py` — every `src/*.py` (minus exemptions) has a partner `tests/test_*.py`, every test passes.
- [ ] No transition shims, deprecated functions, or "TODO(#N+)" markers referencing closed issues.
- [ ] All forcing-function tests have been replaced by real behaviour tests where the issue they were designed to surface has landed.
- [ ] No mock-heavy tests testing implementation details — tests verify behaviour through public interfaces (per `docs/TESTING.md`).
- [ ] All `src/*.py` modules have a one-line module docstring (surfaces in MAP.md glossary).

## Knowledge base

- [ ] `uv run python -m src.ingest` — KB re-ingested against current `data/knowledge_base/`. Chunk count matches expected (look for unexplained drops or jumps).
- [ ] No stale tense/dates: every "present" / "currently" reference matches reality (e.g. completed roles past-tensed, current role accurate).
- [ ] `data/profile.md` Frame sections match the latest profile (gap_inventory, active_learning, narrative_summary all current).
- [ ] No real-name references to people not authorised (collaborators / supervisors only where in scope).

## Eval

- [ ] `eval/run_eval.py` has been rewired through the routed pipeline (no leftover `answer_question` stub failures).
- [ ] Latest eval baseline run against the deployed system stored in `eval/results/` with date stamp.
- [ ] Comparison against prior baseline noted in `DECISIONS.md` with caveats (routing reshapes retrieval — not apples-to-apples vs pre-redesign).

## Live behaviour

- [ ] All branches return the right calibration verb on direct probes (`HUMAN_EVAL_QUESTIONS.md`).
- [ ] In-progress curriculum keywords (Bedrock, Aurora Serverless, Terraform, etc.) never claimed as acquired skills (system-failure target).
- [ ] Adversarial probes (social pressure, list-implicit asks) hold the line.
- [ ] Mid-conversation branch flips work — same session, different turns route correctly.
- [ ] Out-of-scope probe declines politely; injection probe refuses and answers the legitimate part.
- [ ] Contact flow works (#16) — form surfaces when offered, `contact_provided` flag flips in the log.

## Observability

- [ ] Sentinel reads from production log location (HF Dataset in prod, JSONL in dev).
- [ ] Every record carries the full enriched schema — no missing fields.
- [ ] Sentinel surfaces the metrics it was designed to: gap rate, deflection rate, misclassification rate (high-confidence-but-fell-back-to-GENERIC), retry rate, answered/refused split.
- [ ] **Canary baseline frozen and current** (#39). `data/canaries/baseline.json` exists; `frozen_git_sha` is within ~5 commits of `HEAD` AND the `frozen_at` date is within ~30 days. If either drifts, run `uv run python src/canary_runner.py --freeze-baseline` to refresh before shipping. (`LIMITATIONS::P12` — stale-baseline noise.)
- [ ] **Canary corpus audited** against current KB content. After any KB rewrite that changes >20% of section content, walk `data/canaries/corpus.json` line-by-line; replace questions whose grounding was removed; add questions for new flagship content. Re-baseline after audit. (`LIMITATIONS::P13` — corpus content drift.)
- [ ] **Live-vs-canary separation verified** — total records on disk = live-default + canary-only. Sanity check after any pipeline / writer changes:
  ```python
  from log_reader import LocalReader
  from dashboard_model import DashboardModel
  records = LocalReader().read()
  live = DashboardModel(records).total_interactions
  canary = DashboardModel(records, include_canary=True, only_canary=True).total_interactions
  assert live + canary == len(records), "live/canary split is broken"
  ```

## Deployment

- [ ] `.env` keys documented (`.env.example` or equivalent).
- [ ] Required services accessible from deployment target (OpenAI, Anthropic, ChromaDB or HF Dataset).
- [ ] Hosting target verified working end-to-end (HF Spaces / Modal / wherever).
- [ ] Public URL responsive; first response under acceptable latency.

## Portfolio / external

- [ ] README current (project overview, how to run, link to deployed instance).
- [ ] LICENSE file present.
- [ ] Portfolio site **embeds** the deployed Space as an iframe on the home page (`AlejandroFuentePinero/alejandrofuentepinero.github.io`), with a plain-text fallback link for clients that block iframes. Verified working on desktop + mobile; no double-scrollbar, no theme jarring, contact form submits successfully from inside the iframe.
- [ ] Public links in `data/raw_me/` work (no 404s, no broken cert badges).
- [ ] **UI polish session shipped** — dedicated standalone session per `docs/TODO.md::Open implementation details`. Concrete gates: welcome message + framing reviewed; theme cohesion across chat / accordion / form / buttons; mobile responsiveness tested at common breakpoints (375px / 768px / 1024px); form layout polish (visual hierarchy, spacing, microcopy beyond Session 26's quick Accordion fix); loading/streaming states for assistant replies; visual feedback during multi-second TECHNICAL tool fetches; error-state UI for `CANNED_REFUSAL` (currently appears as a regular assistant message). Recruiter-facing presentation matters as much as the routed-pipeline correctness — both are load-bearing for the portfolio function.
- [ ] Every Source link in `data/readmes/*.md` resolves for unauthenticated visitors (no private repos, no broken DOIs). Smoke-test with: `grep -hoE 'https?://[^[:space:])]+' data/readmes/*.md | sort -u | while read u; do echo "$(curl -L -s -o /dev/null -w '%{http_code}' --max-time 15 "$u")  $u"; done`. Wiley journal URLs return 403 to scripted requests but resolve in browsers — verify those manually.
- [ ] [`data/readmes/digital_twin.md`](../data/readmes/digital_twin.md) replaced with Alejandro-authored content (currently a Claude-authored placeholder per `docs/TODO.md::Open implementation details`). Voice and emphasis are the recruiter-facing surface for "how does this very chatbot work?" — content must read in Alejandro's voice. Keep the locked Q11 shape (Source link → What it is → Architecture → Key engineering decisions → Stack and discipline).
- [ ] [`data/readmes/digital_twin.md`](../data/readmes/digital_twin.md) Source link resolves: either the `AlejandroFuentePinero/digital-twin` repo is made public (`gh repo edit AlejandroFuentePinero/digital-twin --visibility public`) so the GitHub URL works, OR the Source line points to an alternative public resource (portfolio page, blog post). Currently the link returns 404 for visitors because the repo is private.

## Final

- [ ] Tag the release commit (`git tag v1.0.0` or similar).
- [ ] Close any remaining `needs-triage` labels — every open issue has been triaged into either a labelled future-state issue or wontfix.
- [ ] Last session entry in DECISIONS.md is dated and final.

# Testing Convention

## The rule

Every `*.py` under `src/` and `eval/` has a matching `tests/test_<module>.py` containing at least one functional test.

New `test_*.py` files appear automatically in the module-health dashboard (`uv run python src/module_health.py`) — no registration step.

## What good tests look like here

- **Mock only at I/O boundaries** — LLM calls (`litellm.completion`, the OpenAI/Anthropic SDKs), DB queries, network. Never mock the module's own helpers.
- **Pure functions are tested directly** with no mocks at all (e.g. metric helpers in `eval/run_eval.py`, the parser in `module_health.py`).
- **Real I/O when cheap** is preferred over mocking it — `tmp_path` for filesystem, real KB markdown files for ingest tests.
- **Assertions describe externally observable behavior**, not implementation details. A test should survive an internal refactor.
- **No LLM API calls in any test, under any circumstances.** The eval pipeline (`eval/run_eval.py` + `eval/tests.jsonl`) is the only place that hits real LLMs. Unit tests stay fast and deterministic so the suite can run on every save.
- **Every test has a one-line docstring.** The module-health dashboard renders the docstring as the test's label, so it should read like a behaviour statement (e.g. `"merge_chunks deduplicates so the LLM never sees the same content twice."`). If a test has no docstring, the dashboard falls back to a humanized name — fine as a temporary state, not as a steady state.

## Exemptions

These files have no matching `test_*.py` because they have no testable behavior:

| File | Reason |
| --- | --- |
| `src/app.py` | Gradio glue — verified by launching the chat UI |
| `src/sample_chunks.py` | One-off diagnostic script |
| `eval/plot_eval.py` | Matplotlib glue — verified visually |

`src/module_health.py` is a partial exemption: its pure helpers (`humanize`, `parse_report`) are covered in `tests/test_module_health.py`; the Gradio rendering, subprocess invocation, and `build_app()` wiring are not — they are tooling glue, verified by launching the dashboard.

`src/sentinel.py` follows the same partial-exemption pattern: its pure formatters (`format_header`, `format_panel`) are covered in `tests/test_sentinel.py` alongside a `build_app()` smoke test (synthetic + live JSONL, no `.launch()`); the Gradio panel layout and refresh-button wiring are verified by running the dashboard locally.

## The dashboard

Launched with `uv run python src/module_health.py` — auto-opens in the default browser.

`src/module_health.py` runs the suite via subprocess on launch and renders:

- A **KPI strip** at the top: a status tile (✅ All passing / ❌ Failures present), discrete count tiles for pass / fail / error / skip with status colours (zeros dimmed), and meta tiles for total duration and last-run timestamp.
- A small **Run all** button (top-right of the header) that re-runs the full suite mid-session and refreshes the KPI strip plus every module card.
- One **collapsible card** per `test_*.py`, distributed across two columns balanced by test count (greedy bin-pack, not by module count). Cards are collapsed by default when all tests in the module pass and **auto-open when any test fails or errors**, so failures are immediately visible without clicking. The header shows a chevron, a status dot, the module name, and an `X/Y` count pill (green tint when all pass, red tint when any fail).
- Inside an open card: one row per test with a subtle status pill (PASS / FAIL / ERROR / SKIP) and the test's docstring-derived label (humanized fallback when absent). Failed tests render their short traceback inline in a styled `<pre>` block with a red left-border accent.

If pytest fails to launch (e.g. the binary moved, dependency broke), the dashboard falls back to rendering the cached `.module_health_report.json` from disk and surfaces the launch error in a banner. When no cached report exists yet, an empty dashboard renders without crashing. Cached report lives at `.module_health_report.json` (gitignored).

Filename intentionally avoids `test_*.py` / `*_test.py` so `uv run pytest` does not auto-collect it and accidentally launch the Gradio app.

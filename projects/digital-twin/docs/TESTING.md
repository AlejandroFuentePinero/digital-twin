# Testing Convention

## The rule

Every `*.py` under `projects/digital-twin/src/` and `projects/digital-twin/eval/` has a matching `projects/digital-twin/tests/test_<module>.py` containing at least one functional test.

New `test_*.py` files appear automatically in the module-health dashboard (`uv run python projects/digital-twin/src/module_health.py`) — no registration step.

## What good tests look like here

- **Mock only at I/O boundaries** — LLM calls (`litellm.completion`, the OpenAI/Anthropic SDKs), DB queries, network. Never mock the module's own helpers.
- **Pure functions are tested directly** with no mocks at all (e.g. metric helpers in `eval/run_eval.py`, the parser in `module_health.py`).
- **Real I/O when cheap** is preferred over mocking it — `tmp_path` for filesystem, real KB markdown files for ingest tests.
- **Assertions describe externally observable behavior**, not implementation details. A test should survive an internal refactor.
- **No LLM API calls in any test, under any circumstances.** The eval pipeline (`eval/run_eval.py` + `eval/tests.jsonl`) is the only place that hits real LLMs. Unit tests stay fast and deterministic so the suite can run on every save.

## Exemptions

These files have no matching `test_*.py` because they have no testable behavior:

| File | Reason |
| --- | --- |
| `src/app.py` | Gradio glue — verified by launching the chat UI |
| `src/sample_chunks.py` | One-off diagnostic script |
| `eval/plot_eval.py` | Matplotlib glue — verified visually |

`src/module_health.py` is a partial exemption: its pure helpers (`humanize`, `parse_report`) are covered in `tests/test_module_health.py`; the Gradio rendering, subprocess invocation, and `build_app()` wiring are not — they are tooling glue, verified by launching the dashboard.

## The dashboard

`projects/digital-twin/src/module_health.py` runs the suite via subprocess on launch and renders one always-visible block per `test_*.py`, with a header `<module> · X/Y` and a coloured PASS / FAIL / ERROR / SKIP badge per test. Cached report lives at `.module_health_report.json` (gitignored).

Filename intentionally avoids `test_*.py` / `*_test.py` so `uv run pytest` does not auto-collect it and accidentally launch the Gradio app.

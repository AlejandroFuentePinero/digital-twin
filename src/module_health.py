"""Local Gradio dashboard showing pass/fail status of digital-twin tests.

Filename intentionally avoids `test_*.py` / `*_test.py` so pytest does not
auto-collect this file.
"""

import ast
import html
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import gradio as gr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"
_REPORT_PATH = _REPO_ROOT / ".module_health_report.json"

_STATUS_KEY = {"PASS": "pass", "FAIL": "fail", "ERROR": "error", "SKIP": "skip"}


_STATUS = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}


@dataclass(frozen=True)
class Test:
    __test__: ClassVar[bool] = False
    label: str
    status: str
    traceback: str | None = None


@dataclass(frozen=True)
class Summary:
    passed: int
    failed: int
    error: int
    skipped: int
    duration: float
    created: float

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.error == 0


@dataclass(frozen=True)
class Module:
    name: str
    tests: list[Test]

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.status == "PASS")

    @property
    def total(self) -> int:
        return len(self.tests)


def humanize(name: str) -> str:
    return name.removeprefix("test_").replace("_", " ").capitalize()


def _module_name(path: str) -> str:
    return Path(path).stem.removeprefix("test_")


def _traceback_for(entry: dict) -> str | None:
    for phase in ("call", "setup", "teardown"):
        info = entry.get(phase) or {}
        if info.get("outcome") == "failed" and info.get("longrepr"):
            return info["longrepr"]
    return None


def _docstring_key(nodeid: str) -> str:
    path, _, func_name = nodeid.partition("::")
    return f"{Path(path).name}::{func_name}"


def _to_test(entry: dict, docstrings: dict[str, str]) -> Test:
    _, _, func_name = entry["nodeid"].partition("::")
    docstring = docstrings.get(_docstring_key(entry["nodeid"]))
    label = docstring if docstring else humanize(func_name)
    return Test(
        label=label,
        status=_STATUS[entry["outcome"]],
        traceback=_traceback_for(entry),
    )


def summarize(report: dict) -> Summary:
    s = report.get("summary", {})
    return Summary(
        passed=s.get("passed", 0),
        failed=s.get("failed", 0),
        error=s.get("error", 0),
        skipped=s.get("skipped", 0),
        duration=report.get("duration", 0.0),
        created=report.get("created", 0.0),
    )


def parse_report(report: dict, docstrings: dict[str, str] | None = None) -> list[Module]:
    docstrings = docstrings or {}
    grouped: dict[str, list[Test]] = defaultdict(list)
    for entry in report.get("tests", []):
        path, _, _ = entry["nodeid"].partition("::")
        grouped[path].append(_to_test(entry, docstrings))
    return [Module(name=_module_name(path), tests=tests) for path, tests in grouped.items()]


def load_docstrings(tests_dir: Path) -> dict[str, str]:
    """Parse `test_*.py` files under `tests_dir` and return {filename::func: docstring}."""
    result: dict[str, str] = {}
    for path in sorted(tests_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                doc = ast.get_docstring(node)
                if doc:
                    result[f"{path.name}::{node.name}"] = doc
    return result


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _badge(status: str) -> str:
    """Subtle status pill — translucent fill, bright text, dark-mode friendly."""
    key = _STATUS_KEY[status]
    return f'<span class="status-pill {key}">{status}</span>'


def _format_date(created: float) -> str:
    if not created:
        return "—"
    return datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d")


def _format_time(created: float) -> str:
    if not created:
        return "—"
    return datetime.fromtimestamp(created, tz=timezone.utc).strftime("%H:%M:%S UTC")


def render_summary(summary: Summary) -> str:
    indicator = "✅" if summary.all_passed else "❌"
    status_label = "All passing" if summary.all_passed else "Failures present"
    status_class = "pass" if summary.all_passed else "fail"
    counts = [
        ("PASS", summary.passed, "pass"),
        ("FAIL", summary.failed, "fail"),
        ("ERROR", summary.error, "error"),
        ("SKIP", summary.skipped, "skip"),
    ]
    count_tiles = "".join(
        f'<div class="kpi {kind}{" zero" if value == 0 else ""}">'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-label">{label}</div>'
        f"</div>"
        for label, value, kind in counts
    )
    return (
        f'<div class="kpi-row">'
        f'<div class="kpi kpi-status {status_class}">'
        f'<div class="kpi-icon">{indicator}</div>'
        f'<div class="kpi-status-text">'
        f'<div class="kpi-status-label">Suite status</div>'
        f'<div class="kpi-status-value">{status_label}</div>'
        f"</div>"
        f"</div>"
        f"{count_tiles}"
        f'<div class="kpi kpi-meta">'
        f'<div class="kpi-value">{summary.duration:.2f}s</div>'
        f'<div class="kpi-label">Duration</div>'
        f"</div>"
        f'<div class="kpi kpi-meta">'
        f'<div class="kpi-value">{_format_time(summary.created)}</div>'
        f'<div class="kpi-label">{_format_date(summary.created)}</div>'
        f"</div>"
        f"</div>"
    )


def render_module(module: Module) -> str:
    state = "pass" if module.passed == module.total else "fail"
    # Auto-open modules that have any FAIL/ERROR so failures are immediately visible.
    open_attr = " open" if state == "fail" else ""
    rows = []
    for t in module.tests:
        rows.append(
            f'<div class="test-row">'
            f"{_badge(t.status)}"
            f'<span class="test-label">{_escape(t.label)}</span>'
            f"</div>"
        )
        if t.traceback:
            rows.append(f'<pre class="traceback">{_escape(t.traceback)}</pre>')
    return (
        f'<details class="module-card"{open_attr}>'
        f'<summary class="module-header">'
        f'<span class="chevron"></span>'
        f'<span class="module-status-dot {state}"></span>'
        f'<span class="module-name">{module.name}</span>'
        f'<span class="module-count {state}">{module.passed}/{module.total}</span>'
        f"</summary>"
        f'<div class="module-tests">{"".join(rows)}</div>'
        f"</details>"
    )


def run_pytest() -> dict:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_TESTS_DIR),
            "--json-report",
            f"--json-report-file={_REPORT_PATH}",
            "--tb=short",
        ],
        capture_output=True,
        cwd=_REPO_ROOT,
    )
    return json.loads(_REPORT_PATH.read_text())


_EMPTY_REPORT: dict = {"summary": {}, "tests": []}


def gather_report(
    runner=run_pytest, cache_path: Path = _REPORT_PATH
) -> tuple[dict, str | None]:
    """Run pytest; on launch failure fall back to the cached JSON on disk.

    Returns (report, error). ``error`` is ``None`` when the runner succeeded;
    otherwise it carries a short description of why pytest didn't run, so the
    UI can surface it. If neither pytest nor the cache produce a usable
    report, an empty report is returned so downstream renderers don't crash.
    """
    try:
        return runner(), None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        try:
            return json.loads(cache_path.read_text()), error
        except (FileNotFoundError, json.JSONDecodeError):
            return _EMPTY_REPORT, error


def _render_error(error: str | None) -> str:
    if not error:
        return ""
    return (
        f'<div style="background:#fee2e2;color:#991b1b;padding:8px 12px;'
        f'border-radius:4px;margin:8px 0">⚠️ pytest failed to launch — showing '
        f"cached report. {_escape(error)}</div>"
    )


def _discover_module_names() -> list[str]:
    """The fixed slot list for the dashboard — derived from filenames on disk."""
    return sorted(p.stem.removeprefix("test_") for p in _TESTS_DIR.glob("test_*.py"))


def _test_counts() -> dict[str, int]:
    """Count tests per module by parsing source — used for column packing pre-launch."""
    counts: dict[str, int] = {}
    for path in _TESTS_DIR.glob("test_*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        n = sum(
            1
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
        counts[path.stem.removeprefix("test_")] = n
    return counts


def _pack_columns(module_names: list[str], counts: dict[str, int]) -> tuple[list[str], list[str]]:
    """Greedy bin-packing: assign each module (largest first) to the shorter column."""
    left: list[str] = []
    right: list[str] = []
    left_load = right_load = 0
    for name in sorted(module_names, key=lambda n: counts.get(n, 0), reverse=True):
        if left_load <= right_load:
            left.append(name)
            left_load += counts.get(name, 0)
        else:
            right.append(name)
            right_load += counts.get(name, 0)
    return left, right


def _refresh_for(module_names: list[str]) -> tuple[str, str, list[str]]:
    report, error = gather_report()
    docstrings = load_docstrings(_TESTS_DIR)
    summary_md = render_summary(summarize(report))
    modules = parse_report(report, docstrings=docstrings)
    by_name = {m.name: m for m in modules}
    empty = '<div class="module-card module-card-static"><div class="module-header"><span class="module-name">{name}</span></div><div class="module-empty">No tests collected.</div></div>'
    bodies = [
        render_module(by_name[n]) if n in by_name else empty.format(name=n)
        for n in module_names
    ]
    return _render_error(error), summary_md, bodies


_DASHBOARD_CSS = """
.dashboard-header { display: flex; align-items: center; gap: 16px; margin-bottom: 4px; }
.dashboard-header h1 { margin: 0; font-size: 1.6em; font-weight: 700; }

.kpi-row {
    display: flex; gap: 10px; flex-wrap: wrap;
    margin: 8px 0 16px 0;
}
.kpi {
    flex: 1; min-width: 88px;
    border: 1px solid var(--border-color-primary, #334155);
    border-radius: 10px;
    padding: 10px 14px;
    background: var(--block-background-fill);
}
.kpi-value { font-size: 1.5em; font-weight: 700; line-height: 1.1; }
.kpi-label {
    font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--body-text-color-subdued, #94a3b8);
    margin-top: 4px;
}
.kpi.pass .kpi-value { color: #4ade80; }
.kpi.fail .kpi-value { color: #f87171; }
.kpi.error .kpi-value { color: #fb923c; }
.kpi.skip .kpi-value { color: #cbd5e1; }
.kpi.zero .kpi-value { color: var(--body-text-color-subdued, #64748b); opacity: 0.55; }
.kpi.kpi-meta .kpi-value { font-size: 1.05em; font-weight: 600; }

.kpi-status {
    flex: 0 1 220px;
    display: flex; align-items: center; gap: 12px;
    border-color: rgba(74, 222, 128, 0.4);
    background: rgba(22, 163, 74, 0.10);
}
.kpi-status.fail {
    border-color: rgba(248, 113, 113, 0.4);
    background: rgba(220, 38, 38, 0.10);
}
.kpi-status .kpi-icon { font-size: 1.6em; line-height: 1; }
.kpi-status-label {
    font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--body-text-color-subdued, #94a3b8);
}
.kpi-status-value { font-size: 1.05em; font-weight: 600; margin-top: 2px; }

.module-card {
    border: 1px solid var(--border-color-primary, #334155);
    border-radius: 10px;
    margin-bottom: 12px;
    background: var(--block-background-fill);
    overflow: hidden;
}
details.module-card[open] { background: var(--block-background-fill); }

.module-header {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px;
    cursor: pointer;
    list-style: none;
    user-select: none;
    transition: background 0.15s;
}
.module-header:hover { background: rgba(255, 255, 255, 0.03); }
.module-header::-webkit-details-marker { display: none; }
.module-header::marker { content: ""; }
details.module-card[open] > .module-header {
    border-bottom: 1px solid var(--border-color-primary, #334155);
    background: rgba(255, 255, 255, 0.02);
}

.chevron {
    display: inline-block;
    width: 10px; height: 10px;
    flex-shrink: 0;
    transition: transform 0.15s ease;
    color: var(--body-text-color-subdued, #94a3b8);
    font-size: 0.85em;
    line-height: 1;
}
.chevron::before { content: "▸"; }
details.module-card[open] > .module-header .chevron { transform: rotate(90deg); }
.module-status-dot {
    width: 9px; height: 9px; border-radius: 50%;
    display: inline-block; flex-shrink: 0;
    box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.18);
}
.module-status-dot.pass { background: #4ade80; }
.module-status-dot.fail {
    background: #f87171;
    box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.18);
}
.module-name {
    font-weight: 700; font-size: 1em;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    letter-spacing: -0.01em;
}
.module-count {
    margin-left: auto;
    font-size: 0.78em; font-weight: 600;
    padding: 3px 10px; border-radius: 999px;
    background: rgba(74, 222, 128, 0.15); color: #4ade80;
}
.module-count.fail { background: rgba(248, 113, 113, 0.15); color: #f87171; }

.module-empty { padding: 14px 16px; color: var(--body-text-color-subdued, #94a3b8); font-style: italic; }

.module-tests { padding: 4px 0; }
.test-row {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 7px 16px;
    font-size: 0.92em; line-height: 1.5;
}
.test-row + .test-row { border-top: 1px solid rgba(148, 163, 184, 0.06); }

.status-pill {
    flex: 0 0 auto;
    font-size: 0.66em; font-weight: 700; letter-spacing: 0.05em;
    padding: 3px 8px; border-radius: 4px;
    margin-top: 3px; min-width: 46px; text-align: center;
}
.status-pill.pass  { background: rgba(74, 222, 128, 0.14); color: #4ade80; }
.status-pill.fail  { background: rgba(248, 113, 113, 0.16); color: #f87171; }
.status-pill.error { background: rgba(251, 146, 60, 0.16); color: #fb923c; }
.status-pill.skip  { background: rgba(148, 163, 184, 0.16); color: #cbd5e1; }

.test-label { flex: 1; word-break: break-word; }

.traceback {
    margin: 6px 16px 12px 16px;
    padding: 10px 12px;
    background: rgba(0, 0, 0, 0.35);
    color: #e2e8f0;
    border-radius: 6px;
    font-size: 0.78em;
    white-space: pre-wrap;
    overflow-x: auto;
    border-left: 3px solid #f87171;
}

#run-all-btn { max-width: 140px; }
"""


def build_app() -> gr.Blocks:
    module_names = _discover_module_names()
    counts = _test_counts()
    left_names, right_names = _pack_columns(module_names, counts)
    error_text, summary_text, bodies = _refresh_for(module_names)
    body_by_name = dict(zip(module_names, bodies))

    with gr.Blocks(title="Digital Twin · Module Health", css=_DASHBOARD_CSS) as app:
        with gr.Row():
            gr.Markdown("# Digital Twin · Module Health")
            run_all = gr.Button(
                "↻ Run all",
                variant="secondary",
                size="sm",
                scale=0,
                elem_id="run-all-btn",
            )
        error_md = gr.Markdown(error_text)
        summary_md = gr.Markdown(summary_text)

        components: dict[str, gr.Markdown] = {}
        with gr.Row(equal_height=False):
            with gr.Column():
                for name in left_names:
                    components[name] = gr.Markdown(body_by_name[name])
            with gr.Column():
                for name in right_names:
                    components[name] = gr.Markdown(body_by_name[name])

        ordered_outputs = [components[n] for n in module_names]

        def _refresh_all():
            error, summary, body_list = _refresh_for(module_names)
            return [error, summary, *body_list]

        run_all.click(
            fn=_refresh_all,
            outputs=[error_md, summary_md, *ordered_outputs],
        )
    return app


if __name__ == "__main__":
    build_app().launch(inbrowser=True)

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
from pathlib import Path
from typing import ClassVar

import gradio as gr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"
_REPORT_PATH = _REPO_ROOT / ".module_health_report.json"

_BADGE_COLOR = {"PASS": "#16a34a", "FAIL": "#dc2626", "ERROR": "#ea580c", "SKIP": "#6b7280"}


_STATUS = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}


@dataclass(frozen=True)
class Test:
    __test__: ClassVar[bool] = False
    label: str
    status: str
    traceback: str | None = None


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
    color = _BADGE_COLOR[status]
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:4px;font-weight:600;font-size:0.85em">{status}</span>'
    )


def render_module(module: Module) -> str:
    lines = [f"### {module.name} · {module.passed}/{module.total}"]
    for t in module.tests:
        lines.append(f"- {_badge(t.status)} {t.label}")
        if t.traceback:
            lines.append(f"<pre style=\"margin:4px 0 8px 24px;padding:8px;"
                         f"background:#0f172a;color:#e2e8f0;border-radius:4px;"
                         f"font-size:0.8em;white-space:pre-wrap;overflow-x:auto\">"
                         f"{_escape(t.traceback)}</pre>")
    return "\n".join(lines)


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


def build_app() -> gr.Blocks:
    modules = parse_report(run_pytest(), docstrings=load_docstrings(_TESTS_DIR))
    with gr.Blocks(title="Digital Twin · Module Health") as app:
        gr.Markdown("# Digital Twin · Module Health")
        for module in modules:
            gr.Markdown(render_module(module))
    return app


if __name__ == "__main__":
    build_app().launch()

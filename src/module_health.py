"""Local Gradio dashboard showing pass/fail status of digital-twin tests.

Filename intentionally avoids `test_*.py` / `*_test.py` so pytest does not
auto-collect this file.
"""

import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import gradio as gr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"
_REPORT_PATH = _REPO_ROOT / ".module_health_report.json"

_BADGE_COLOR = {"PASS": "#16a34a", "FAIL": "#dc2626", "ERROR": "#ea580c", "SKIP": "#6b7280"}


_STATUS = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}


@dataclass(frozen=True)
class Test:
    label: str
    status: str


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


def _to_test(entry: dict) -> Test:
    _, _, func_name = entry["nodeid"].partition("::")
    return Test(label=humanize(func_name), status=_STATUS[entry["outcome"]])


def parse_report(report: dict) -> list[Module]:
    grouped: dict[str, list[Test]] = defaultdict(list)
    for entry in report.get("tests", []):
        path, _, _ = entry["nodeid"].partition("::")
        grouped[path].append(_to_test(entry))
    return [Module(name=_module_name(path), tests=tests) for path, tests in grouped.items()]


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
    modules = parse_report(run_pytest())
    with gr.Blocks(title="Digital Twin · Module Health") as app:
        gr.Markdown("# Digital Twin · Module Health")
        for module in modules:
            gr.Markdown(render_module(module))
    return app


if __name__ == "__main__":
    build_app().launch()

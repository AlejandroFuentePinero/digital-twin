"""System map generator — walks src/ and emits docs/MAP.md.

Parses each `src/*.py` via `ast`, extracts the module docstring's first line as
the glossary entry, and the static imports as graph edges. Internal imports
(siblings in `src/`) become edges between modules; known external imports
(litellm, anthropic, chromadb, etc.) become edges to a separate "external
services" cluster.

Run with `uv run python src/system_map.py` — overwrites `docs/MAP.md`.
"""

from __future__ import annotations

import ast
import webbrowser
from pathlib import Path

SRC_DIR = Path(__file__).parent
DOCS_DIR = SRC_DIR.parent / "docs"
MAP_PATH = DOCS_DIR / "MAP.md"
HTML_PATH = DOCS_DIR / "MAP.html"
PIPELINE_DIAGRAM_PATH = DOCS_DIR / "pipeline_diagram.mmd"

EXTERNAL_SERVICES: dict[str, str] = {
    "litellm": "OpenAI / Anthropic API (via LiteLLM)",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "chromadb": "ChromaDB",
    "datasets": "HuggingFace Dataset",
    "huggingface_hub": "HuggingFace Hub",
    "gradio": "Gradio (UI)",
}

NO_DOCSTRING_SENTINEL = "(no description — add a module docstring)"

# Every module in src/ must appear here. The forcing-function test in
# tests/test_system_map.py fails when a new module lands without a category.
MODULE_CATEGORY: dict[str, str] = {
    "rules": "Frame & Rules",
    "branches": "Frame & Rules",
    "profile": "Frame & Rules",
    "composer": "Frame & Rules",
    "classifier": "LLM Callers",
    "generator": "LLM Callers",
    "guardrail": "LLM Callers",
    "retrieval": "Retrieval (RAG)",
    "ingest": "Retrieval (RAG)",
    "interaction_log": "Logging",
    "log_reader": "Logging",
    "session_state": "Logging",
    "contact_log": "Logging",
    "pipeline": "Pipeline",
    "tools": "Tools",
    "tool_loop": "Tools",
    "app": "App / UI",
    "module_health": "Tooling",
    "system_map": "Tooling",
    "sample_chunks": "Tooling",
    "sentinel": "Tooling",
    "dashboard_model": "Tooling",
    "metric_status": "Tooling",
    "failure_feed": "Tooling",
    "replayer": "Tooling",
    "cluster_gaps": "Tooling",
    "summarize_failures": "Tooling",
}

UNCATEGORIZED = "Uncategorized"

# Vibrant saturated palette (Tailwind 500-shade family) with white text on solid fills.
# `bg` is the lighter shade used as the subgraph cluster background (Tailwind 100).
CATEGORY_STYLES: dict[str, dict[str, str]] = {
    "Frame & Rules":             {"id": "frame",     "fill": "#6366f1", "stroke": "#4338ca", "color": "#ffffff", "bg": "#eef2ff", "border": "#a5b4fc"},
    "LLM Callers":               {"id": "llm",       "fill": "#f59e0b", "stroke": "#b45309", "color": "#ffffff", "bg": "#fef3c7", "border": "#fcd34d"},
    "Retrieval (RAG)":           {"id": "retrieval", "fill": "#10b981", "stroke": "#047857", "color": "#ffffff", "bg": "#d1fae5", "border": "#6ee7b7"},
    "Pipeline":                  {"id": "pipeline",  "fill": "#ef4444", "stroke": "#b91c1c", "color": "#ffffff", "bg": "#fee2e2", "border": "#fca5a5"},
    "Tools":                     {"id": "tools",     "fill": "#06b6d4", "stroke": "#0e7490", "color": "#ffffff", "bg": "#cffafe", "border": "#67e8f9"},
    "Logging":                   {"id": "logging",   "fill": "#ec4899", "stroke": "#be185d", "color": "#ffffff", "bg": "#fce7f3", "border": "#f9a8d4"},
    "App / UI":                  {"id": "appui",     "fill": "#3b82f6", "stroke": "#1d4ed8", "color": "#ffffff", "bg": "#dbeafe", "border": "#93c5fd"},
    "Legacy (transition shim)":  {"id": "legacy",    "fill": "#94a3b8", "stroke": "#475569", "color": "#ffffff", "bg": "#f1f5f9", "border": "#cbd5e1", "dashed": "true"},
    "Tooling":                   {"id": "tooling",   "fill": "#8b5cf6", "stroke": "#6d28d9", "color": "#ffffff", "bg": "#ede9fe", "border": "#c4b5fd"},
    "External Services":         {"id": "external",  "fill": "#f97316", "stroke": "#c2410c", "color": "#ffffff", "bg": "#fff7ed", "border": "#fdba74"},
    UNCATEGORIZED:               {"id": "uncat",     "fill": "#9ca3af", "stroke": "#4b5563", "color": "#ffffff", "bg": "#f9fafb", "border": "#d1d5db"},
}


def parse_module(path: Path) -> tuple[str, list[str]]:
    """Return (first line of the module docstring, list of top-level imports)."""
    tree = ast.parse(path.read_text())
    docstring = ast.get_docstring(tree) or ""
    first_line = docstring.strip().split("\n", 1)[0].strip() if docstring else ""

    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
    return first_line, imports


def _list_modules(src_dir: Path) -> list[str]:
    return sorted(p.stem for p in src_dir.glob("*.py") if not p.stem.startswith("_"))


def build_graph(src_dir: Path) -> dict:
    """Walk `src_dir`, parse each module, return modules / internal / external edges / glossary."""
    modules = _list_modules(src_dir)
    module_set = set(modules)

    internal_edges: list[tuple[str, str]] = []
    external_edges: list[tuple[str, str]] = []
    glossary: dict[str, str] = {}

    for m in modules:
        first_line, imports = parse_module(src_dir / f"{m}.py")
        glossary[m] = first_line or NO_DOCSTRING_SENTINEL
        for imp in imports:
            if imp == m:
                continue
            if imp in module_set:
                edge = (m, imp)
                if edge not in internal_edges:
                    internal_edges.append(edge)
            elif imp in EXTERNAL_SERVICES:
                edge = (m, EXTERNAL_SERVICES[imp])
                if edge not in external_edges:
                    external_edges.append(edge)

    return {
        "modules": modules,
        "internal_edges": internal_edges,
        "external_edges": external_edges,
        "glossary": glossary,
    }


def _classdef_line(category: str) -> str:
    style = CATEGORY_STYLES[category]
    parts = [
        f"fill:{style['fill']}",
        f"stroke:{style['stroke']}",
        f"color:{style['color']}",
        "stroke-width:2px",
    ]
    if style.get("dashed") == "true":
        parts.append("stroke-dasharray:5 4")
    return f"  classDef {style['id']} {','.join(parts)}"


def _subgraph_style_line(category: str) -> str:
    """Tints the subgraph cluster background with the category's lighter shade."""
    style = CATEGORY_STYLES[category]
    return (
        f"  style sg_{style['id']} "
        f"fill:{style['bg']},stroke:{style['border']},stroke-width:1.5px,color:{style['stroke']}"
    )


def _emit_mermaid(graph: dict) -> str:
    lines = [
        "```mermaid",
        "%%{init: {'flowchart': {'nodeSpacing': 50, 'rankSpacing': 100, 'curve': 'basis', 'padding': 12}}}%%",
        "graph LR",
    ]

    # classDef declarations — one per category that may appear in this graph
    for category in CATEGORY_STYLES:
        lines.append(_classdef_line(category))
    lines.append("")

    # Group internal modules by category, in CATEGORY_STYLES order
    by_category: dict[str, list[str]] = {cat: [] for cat in CATEGORY_STYLES}
    for module in graph["modules"]:
        cat = MODULE_CATEGORY.get(module, UNCATEGORIZED)
        by_category[cat].append(module)

    used_categories: list[str] = []
    for category, modules in by_category.items():
        if category == "External Services":
            continue
        if not modules:
            continue
        used_categories.append(category)
        style_id = CATEGORY_STYLES[category]["id"]
        subgraph_id = f"sg_{style_id}"
        lines.append(f'  subgraph {subgraph_id}["{category}"]')
        lines.append(f"    direction TB")
        for m in modules:
            lines.append(f'    {m}["{m}.py"]:::{style_id}')
        lines.append("  end")
        lines.append("")

    # External services subgraph
    services = sorted({label for _, label in graph["external_edges"]})
    if services:
        used_categories.append("External Services")
        ext_style_id = CATEGORY_STYLES["External Services"]["id"]
        lines.append('  subgraph sg_external["External Services"]')
        lines.append(f"    direction TB")
        for service in services:
            lines.append(f'    ext_{_slug(service)}(["{service}"]):::{ext_style_id}')
        lines.append("  end")
        lines.append("")

    # Edges
    for src, dst in graph["internal_edges"]:
        lines.append(f"  {src} --> {dst}")
    for src, label in graph["external_edges"]:
        lines.append(f"  {src} --> ext_{_slug(label)}")
    lines.append("")

    # Subgraph cluster backgrounds (placed at the end so they apply over inherited styles)
    for category in used_categories:
        lines.append(_subgraph_style_line(category))

    lines.append("```")
    return "\n".join(lines)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)


def _emit_glossary(graph: dict) -> str:
    lines = ["| Module | Description |", "|---|---|"]
    for m in graph["modules"]:
        lines.append(f"| `{m}.py` | {graph['glossary'][m]} |")
    return "\n".join(lines)


def _load_pipeline_diagram(path: Path | None) -> str | None:
    """Return the contents of a hand-edited Mermaid pipeline diagram, or None if absent."""
    if path is None or not path.exists():
        return None
    return path.read_text().strip() or None


def _emit_pipeline_section_md(diagram: str) -> str:
    return (
        "## Pipeline behaviour (runtime)\n\n"
        "How a user question becomes a response — branch routing, retry loop, side effects, and tool placeholders. "
        "Hand-edited at [`docs/pipeline_diagram.mmd`](./pipeline_diagram.mmd); rerun `uv run python src/system_map.py` "
        "to regenerate this section after editing.\n\n"
        "**Legend:** orange = LLM call · green = pure transform · yellow = decision · pink = side effect · "
        "red = canned refusal · dashed grey = future tool · orange ovals = user I/O.\n\n"
        f"```mermaid\n{diagram}\n```\n\n"
    )


def _emit_pipeline_section_html(diagram: str) -> str:
    return (
        "  <h2>Pipeline behaviour (runtime)</h2>\n"
        '  <p class="meta">How a user question becomes a response. '
        'Hand-edited at <code>docs/pipeline_diagram.mmd</code>. '
        "Legend: orange = LLM · green = pure transform · yellow = decision · pink = side effect · "
        "red = refusal · dashed grey = future tool.</p>\n"
        f'  <pre class="mermaid">\n{diagram}\n  </pre>\n'
    )


def render(src_dir: Path, pipeline_diagram_path: Path | None = None) -> str:
    """Produce the full MAP.md content for `src_dir` as a single string.

    If `pipeline_diagram_path` exists, its Mermaid content is injected as a top-level
    "Pipeline behaviour (runtime)" section above the module graph. Defaults to
    `docs/pipeline_diagram.mmd`; pass `None` (or a non-existent path) to omit.
    """
    if pipeline_diagram_path is None:
        pipeline_diagram_path = PIPELINE_DIAGRAM_PATH
    diagram = _load_pipeline_diagram(pipeline_diagram_path)
    pipeline_section = _emit_pipeline_section_md(diagram) if diagram else ""

    graph = build_graph(src_dir)
    return (
        "# System Map\n\n"
        "Auto-generated by `src/system_map.py`. Do not edit by hand — re-run with "
        "`uv run python src/system_map.py` after touching modules in `src/` or "
        "after editing `docs/pipeline_diagram.mmd`.\n\n"
        "Companion docs: [`CONTEXT.md`](../CONTEXT.md) (domain glossary), "
        "[`docs/adr/`](./adr/) (architectural decisions).\n\n"
        + pipeline_section
        + "## Module graph\n\n"
        + _emit_mermaid(graph)
        + "\n\n"
        "## Glossary\n\n"
        + _emit_glossary(graph)
        + "\n"
    )


def render_html(src_dir: Path, pipeline_diagram_path: Path | None = None) -> str:
    """Standalone HTML preview — pipeline behaviour + module graph + glossary, rendered client-side via CDN."""
    if pipeline_diagram_path is None:
        pipeline_diagram_path = PIPELINE_DIAGRAM_PATH
    diagram = _load_pipeline_diagram(pipeline_diagram_path)
    pipeline_section = _emit_pipeline_section_html(diagram) if diagram else ""

    graph = build_graph(src_dir)
    mermaid_block = "\n".join(_emit_mermaid(graph).splitlines()[1:-1])  # strip ``` fences
    glossary_rows = "".join(
        f'<tr><td><code>{m}.py</code></td><td>{graph["glossary"][m]}</td></tr>'
        for m in graph["modules"]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Digital Twin — System Map</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif; padding: 2em; max-width: 1200px; margin: 0 auto; color: #1a1a1a; }}
    h1 {{ border-bottom: 2px solid #ddd; padding-bottom: 0.4em; }}
    h2 {{ margin-top: 2em; }}
    .mermaid {{ background: white; border: 1px solid #eee; padding: 1em; border-radius: 6px; min-height: 400px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f6f6; }}
    code {{ background: #f6f6f6; padding: 2px 6px; border-radius: 3px; font-family: ui-monospace, monospace; }}
    .meta {{ color: #666; font-size: 0.9em; }}
  </style>
</head>
<body>
  <h1>Digital Twin — System Map</h1>
  <p class="meta">Auto-generated from <code>src/*.py</code> imports + module docstrings, plus the hand-edited pipeline diagram at <code>docs/pipeline_diagram.mmd</code>. Refresh with <code>uv run python src/system_map.py</code>.</p>
{pipeline_section}  <h2>Module graph</h2>
  <pre class="mermaid">
{mermaid_block}
  </pre>
  <h2>Glossary</h2>
  <table>
    <tr><th>Module</th><th>Description</th></tr>
    {glossary_rows}
  </table>
  <script>mermaid.initialize({{ startOnLoad: true, theme: 'default', flowchart: {{ curve: 'basis' }} }});</script>
</body>
</html>
"""


def main() -> None:
    md = render(SRC_DIR)
    MAP_PATH.write_text(md)
    html = render_html(SRC_DIR)
    HTML_PATH.write_text(html)
    print(f"Wrote {MAP_PATH.relative_to(SRC_DIR.parent)} + {HTML_PATH.relative_to(SRC_DIR.parent)}")
    webbrowser.open(HTML_PATH.as_uri())


if __name__ == "__main__":
    main()

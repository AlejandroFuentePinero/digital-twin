from system_map import NO_DOCSTRING_SENTINEL, build_graph, parse_module, render, render_html


def test_parse_module_extracts_top_level_imports(tmp_path):
    """parse_module returns the names of every top-level `import x` and `from x import y` statement."""
    p = tmp_path / "fake.py"
    p.write_text(
        '"""Some module."""\n'
        "from branches import BranchSpec\n"
        "from rules import RULES, UNIVERSAL\n"
        "import litellm\n"
    )
    _, imports = parse_module(p)
    assert set(imports) == {"branches", "rules", "litellm"}


def test_parse_module_returns_first_line_of_module_docstring(tmp_path):
    """parse_module returns the first line of a multi-line module docstring as the glossary entry."""
    p = tmp_path / "fake.py"
    p.write_text(
        '"""First-line summary of the module.\n'
        "\n"
        "More detail on subsequent lines that should not appear.\n"
        '"""\n'
    )
    first_line, _ = parse_module(p)
    assert first_line == "First-line summary of the module."


def test_build_graph_separates_internal_edges_from_external_services(tmp_path):
    """Internal imports become module-to-module edges; known external imports become external-service edges."""
    (tmp_path / "alpha.py").write_text(
        '"""Alpha module."""\n'
        "from beta import thing\n"
        "import litellm\n"
    )
    (tmp_path / "beta.py").write_text('"""Beta module."""\n')
    (tmp_path / "gamma.py").write_text(
        '"""Gamma module."""\n'
        "from beta import other\n"
        "import chromadb\n"
    )

    graph = build_graph(tmp_path)
    assert set(graph["modules"]) == {"alpha", "beta", "gamma"}
    assert ("alpha", "beta") in graph["internal_edges"]
    assert ("gamma", "beta") in graph["internal_edges"]
    assert ("alpha", "OpenAI / Anthropic API (via LiteLLM)") in graph["external_edges"]
    assert ("gamma", "ChromaDB") in graph["external_edges"]
    # Internal edges must not appear in external edges
    assert ("alpha", "beta") not in graph["external_edges"]


def test_build_graph_uses_sentinel_for_missing_docstrings(tmp_path):
    """Modules without a docstring get the NO_DOCSTRING_SENTINEL glossary entry — surfaces missing docs."""
    (tmp_path / "naked.py").write_text("x = 1\n")
    graph = build_graph(tmp_path)
    assert graph["glossary"]["naked"] == NO_DOCSTRING_SENTINEL


def test_render_quotes_labels_so_parentheses_in_service_names_do_not_break_mermaid(tmp_path):
    """External service labels with parens (e.g. 'OpenAI (via LiteLLM)') render as quoted Mermaid labels."""
    (tmp_path / "alpha.py").write_text(
        '"""Alpha."""\nimport litellm\n'
    )
    out = render(tmp_path)
    # Quoted label syntax: id(["Service (with parens)"]) — never bare brackets that Mermaid mis-parses
    assert '(["OpenAI / Anthropic API (via LiteLLM)"])' in out
    # Internal module labels also quoted (defensive)
    assert '["alpha.py"]' in out


def test_render_emits_mermaid_block_and_glossary_table(tmp_path):
    """render() produces a MAP.md string with a ```mermaid block, every internal edge, and a glossary table row per module."""
    (tmp_path / "alpha.py").write_text(
        '"""Alpha does the alpha thing."""\nfrom beta import x\n'
    )
    (tmp_path / "beta.py").write_text('"""Beta does the beta thing."""\n')

    out = render(tmp_path)
    # Mermaid block
    assert "```mermaid" in out
    assert "```" in out
    assert "alpha --> beta" in out
    # Glossary table
    assert "| Module | Description |" in out
    assert "| `alpha.py` | Alpha does the alpha thing. |" in out
    assert "| `beta.py` | Beta does the beta thing. |" in out


def test_render_html_emits_self_contained_preview_with_mermaid_cdn(tmp_path):
    """render_html produces a standalone HTML document loading mermaid.js from CDN, embedding the graph and glossary."""
    (tmp_path / "alpha.py").write_text(
        '"""Alpha does the alpha thing."""\nfrom beta import x\n'
    )
    (tmp_path / "beta.py").write_text('"""Beta does the beta thing."""\n')

    html = render_html(tmp_path)
    assert "<!DOCTYPE html>" in html
    assert "mermaid" in html.lower()
    assert "cdn.jsdelivr.net" in html  # CDN reference
    assert 'class="mermaid"' in html
    # Mermaid block content embedded (without the markdown ```mermaid fence)
    assert "graph LR" in html
    assert "alpha --> beta" in html
    # Glossary content present
    assert "Alpha does the alpha thing." in html
    assert "Beta does the beta thing." in html


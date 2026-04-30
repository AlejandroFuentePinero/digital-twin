from unittest.mock import MagicMock, call, patch

from ingest import ChunkEnrichment, enrich_all, enrich_chunk, load_chunks, split_on_headings


# --- split_on_headings ---


def test_h2_sections_become_separate_chunks():
    text = "# Title\n\n## Section One\nContent one.\n\n## Section Two\nContent two.\n"
    chunks = split_on_headings(text, "test.md", "test")
    assert len(chunks) == 2
    assert chunks[0]["section_heading"] == "Section One"
    assert chunks[0]["heading_level"] == 2
    assert chunks[1]["section_heading"] == "Section Two"
    assert chunks[1]["heading_level"] == 2


def test_h3_headings_are_kept_as_content_within_h2_chunk():
    text = "# Title\n\n## Parent\n\n### Sub A\nContent A.\n\n### Sub B\nContent B.\n"
    chunks = split_on_headings(text, "test.md", "test")
    assert len(chunks) == 1
    assert chunks[0]["section_heading"] == "Parent"
    assert chunks[0]["heading_level"] == 2
    assert "### Sub A" in chunks[0]["text"]
    assert "### Sub B" in chunks[0]["text"]


def test_preamble_with_content_is_kept_as_chunk():
    # publications.md has URLs in the preamble before the first ## heading
    text = "# Publications\n\nFull list: https://scholar.google.com/\nORCID: https://orcid.org/\n\n## First-author papers\nContent.\n"
    chunks = split_on_headings(text, "publications.md", "publications")
    assert len(chunks) == 2
    assert "https://scholar.google.com" in chunks[0]["text"]


def test_preamble_with_only_h1_title_is_discarded():
    text = "# Skills\n\n## Core strength\nContent here.\n"
    chunks = split_on_headings(text, "skills.md", "skills")
    assert len(chunks) == 1
    assert chunks[0]["section_heading"] == "Core strength"


def test_file_with_no_headings_returns_single_chunk():
    text = "# Title\n\nJust some content with no subheadings."
    chunks = split_on_headings(text, "simple.md", "test")
    assert len(chunks) == 1
    assert chunks[0]["heading_level"] == 0


def test_chunk_text_contains_its_heading():
    text = "# Title\n\n## My Section\nSome content under the section.\n"
    chunks = split_on_headings(text, "test.md", "test")
    assert "## My Section" in chunks[0]["text"]


def test_h4_headings_do_not_cause_splits():
    text = "# Title\n\n## Section\nContent.\n\n#### Deep heading\nMore content.\n"
    chunks = split_on_headings(text, "test.md", "test")
    assert len(chunks) == 1
    assert "#### Deep heading" in chunks[0]["text"]


def test_short_section_is_not_filtered_out():
    # No minimum word count — short but real sections must be kept
    text = (
        "# Education\n\n"
        "## Editorial Services (peer reviewer)\n"
        "Functional Ecology · PeerJ · Biodiversity and Conservation\n"
    )
    chunks = split_on_headings(text, "education.md", "education")
    assert len(chunks) == 1
    assert chunks[0]["section_heading"] == "Editorial Services (peer reviewer)"


def test_each_chunk_contains_only_its_own_section_content():
    # Section One's content must not bleed into Section Two and vice versa
    text = (
        "# Title\n\n"
        "## Section One\nExclusive content A.\n\n"
        "## Section Two\nExclusive content B.\n"
    )
    chunks = split_on_headings(text, "test.md", "test")
    assert "Exclusive content A" in chunks[0]["text"]
    assert "Exclusive content A" not in chunks[1]["text"]
    assert "Exclusive content B" in chunks[1]["text"]
    assert "Exclusive content B" not in chunks[0]["text"]


# --- load_chunks ---


def test_summary_is_a_single_unsplit_chunk():
    chunks = load_chunks()
    summary = [c for c in chunks if c["source_file"] == "SUMMARY.md"]
    assert len(summary) == 1


def test_index_is_a_single_unsplit_chunk():
    chunks = load_chunks()
    index = [c for c in chunks if c["source_file"] == "INDEX.md"]
    assert len(index) == 1


def test_multi_section_files_are_split():
    chunks = load_chunks()
    # Both research files have many ## sections — verify they're not stored whole
    for filename in ("publications.md", "research_projects_detail.md", "experience.md"):
        file_chunks = [c for c in chunks if c["source_file"] == filename]
        assert len(file_chunks) > 1, f"{filename} should produce multiple chunks"


def test_all_chunks_have_required_metadata():
    for chunk in load_chunks():
        assert "source_file" in chunk
        assert "section_heading" in chunk
        assert "heading_level" in chunk
        assert "category" in chunk
        assert "text" in chunk
        assert chunk["text"].strip()


def test_category_mapping_is_correct():
    chunks = load_chunks()
    by_file = {c["source_file"]: c["category"] for c in chunks}
    assert by_file["SUMMARY.md"] == "summary"
    assert by_file["INDEX.md"] == "index"
    assert by_file["publications.md"] == "publications"
    assert by_file["projects_ai_flagship.md"] == "projects"
    assert by_file["projects_skill_labs.md"] == "projects"
    assert by_file["research_overview.md"] == "research"
    assert by_file["research_projects_detail.md"] == "research"


# --- enrich_chunk ---


def test_enrich_chunk_output_merges_enrichment_with_original():
    chunk = {
        "text": "Alejandro speaks Spanish natively and English professionally.",
        "section_heading": "Languages",
        "heading_level": 2,
        "source_file": "skills.md",
        "category": "skills",
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = ChunkEnrichment(
        headline="What languages does Alejandro speak?",
        summary="Alejandro is a native Spanish speaker with professional English.",
    )
    with patch("ingest.client.beta.chat.completions.parse", return_value=mock_response):
        enriched = enrich_chunk(chunk)

    # Enrichment fields added
    assert enriched["headline"] == "What languages does Alejandro speak?"
    assert enriched["summary"] == "Alejandro is a native Spanish speaker with professional English."
    # Original fields preserved unchanged
    assert enriched["text"] == chunk["text"]
    assert enriched["section_heading"] == "Languages"
    assert enriched["heading_level"] == 2
    assert enriched["source_file"] == "skills.md"
    assert enriched["category"] == "skills"


def test_enrich_chunk_includes_source_context_in_prompt():
    # The prompt must include source_file and section_heading so the LLM can
    # generate contextually appropriate headlines — dropping either would degrade quality
    chunk = {
        "text": "Some content.",
        "section_heading": "Key Research Skills",
        "heading_level": 2,
        "source_file": "skills.md",
        "category": "skills",
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = ChunkEnrichment(headline="h", summary="s")

    with patch("ingest.client.beta.chat.completions.parse", return_value=mock_response) as mock_call:
        enrich_chunk(chunk)

    prompt = mock_call.call_args[1]["messages"][0]["content"]
    assert "skills.md" in prompt
    assert "Key Research Skills" in prompt


# --- enrich_all ---


def test_enrich_all_preserves_input_order():
    # enrich_all uses ThreadPoolExecutor and as_completed, which completes futures in
    # arbitrary order. The indexing logic must write results back to their original position.
    chunks = [
        {"id": i, "text": f"chunk {i}", "section_heading": f"s{i}",
         "heading_level": 2, "source_file": "test.md", "category": "test"}
        for i in range(10)
    ]

    def mock_enrich(chunk):
        return {**chunk, "headline": f"h{chunk['id']}", "summary": f"s{chunk['id']}"}

    with patch("ingest.enrich_chunk", side_effect=mock_enrich):
        result = enrich_all(chunks)

    assert [c["id"] for c in result] == list(range(10))
    assert [c["headline"] for c in result] == [f"h{i}" for i in range(10)]

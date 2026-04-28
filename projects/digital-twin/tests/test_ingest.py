from unittest.mock import MagicMock, patch

from ingest import ChunkEnrichment, enrich_chunk, load_chunks, split_on_headings


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
    # ### headings are body content inside the ## section, not split points
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


def test_editorial_services_section_is_captured():
    # A real but short section — ensures no length-based filtering
    text = (
        "# Education\n\n"
        "## Editorial Services (peer reviewer)\n"
        "Functional Ecology · PeerJ · Biodiversity and Conservation · One Earth · Ecology and Evolution\n"
    )
    chunks = split_on_headings(text, "education.md", "education")
    assert len(chunks) == 1
    assert chunks[0]["section_heading"] == "Editorial Services (peer reviewer)"


# --- load_chunks ---


def test_summary_is_a_single_unsplit_chunk():
    chunks = load_chunks()
    summary = [c for c in chunks if c["source_file"] == "SUMMARY.md"]
    assert len(summary) == 1


def test_index_is_a_single_unsplit_chunk():
    chunks = load_chunks()
    index = [c for c in chunks if c["source_file"] == "INDEX.md"]
    assert len(index) == 1


def test_other_files_are_split_into_multiple_chunks():
    chunks = load_chunks()
    # publications.md has 7 first-author papers as ### sections plus co-authored section
    pub_chunks = [c for c in chunks if c["source_file"] == "publications.md"]
    assert len(pub_chunks) > 5


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
    assert by_file["research_overview.md"] == "research"


# --- enrich_chunk ---


def test_enrich_chunk_adds_headline_and_summary():
    chunk = {
        "text": "Alejandro speaks Spanish natively and English professionally.",
        "section_heading": "Languages",
        "heading_level": 2,
        "source_file": "skills.md",
        "category": "skills",
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = ChunkEnrichment(
        headline="Languages Alejandro speaks",
        summary="Alejandro is a native Spanish speaker with professional-level English.",
    )
    with patch("ingest.client.beta.chat.completions.parse", return_value=mock_response):
        enriched = enrich_chunk(chunk)

    assert enriched["headline"] == "Languages Alejandro speaks"
    assert enriched["summary"] == "Alejandro is a native Spanish speaker with professional-level English."


def test_enrich_chunk_preserves_original_text():
    original_text = "Some original content that must not be altered."
    chunk = {
        "text": original_text,
        "section_heading": "Test",
        "heading_level": 2,
        "source_file": "test.md",
        "category": "test",
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = ChunkEnrichment(
        headline="Test headline",
        summary="One sentence summary.",
    )
    with patch("ingest.client.beta.chat.completions.parse", return_value=mock_response):
        enriched = enrich_chunk(chunk)

    assert enriched["text"] == original_text


def test_enrich_chunk_preserves_all_metadata():
    chunk = {
        "text": "Content.",
        "section_heading": "My Section",
        "heading_level": 3,
        "source_file": "identity.md",
        "category": "identity",
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = ChunkEnrichment(
        headline="Headline", summary="Summary."
    )
    with patch("ingest.client.beta.chat.completions.parse", return_value=mock_response):
        enriched = enrich_chunk(chunk)

    assert enriched["section_heading"] == "My Section"
    assert enriched["heading_level"] == 3
    assert enriched["source_file"] == "identity.md"
    assert enriched["category"] == "identity"

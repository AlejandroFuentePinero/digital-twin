"""
Ingest the digital twin knowledge base into ChromaDB.

Chunking strategy:
  - SUMMARY.md and INDEX.md are stored as single un-split chunks.
  - All other files are split on ## boundaries only. The knowledge base is structured
    so that every ## section is a complete, self-contained retrieval unit. ### headings
    within a section are body content, not split points.
  - Each chunk is enriched with an LLM-generated headline and one-sentence summary.
  - The embedded document is: headline + summary + original_text.
  - Metadata per chunk: source_file, section_heading, heading_level, category, headline, summary.

Run from the repo root:
  uv run src/ingest.py
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from chromadb import PersistentClient
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from tqdm import tqdm

load_dotenv(override=True)

KB_PATH = Path(__file__).parent.parent / "data" / "knowledge_base"
DB_PATH = str(Path(__file__).parent.parent / "data" / "preprocessed_db")
COLLECTION = "digital_twin"
EMBED_MODEL = "text-embedding-3-large"
ENRICH_MODEL = "gpt-4.1-nano"
WORKERS = 10

UNSPLIT = {"SUMMARY", "INDEX"}

CATEGORY_MAP = {
    "identity": "identity",
    "skills": "skills",
    "experience": "experience",
    "education": "education",
    "projects_ai_flagship": "projects",
    "projects_skill_labs": "projects",
    "research_overview": "research",
    "research_projects_detail": "research",
    "publications": "publications",
    "recognition": "recognition",
    "teaching": "teaching",
    "talks": "talks",
    "personal": "personal",
    "positioning": "positioning",
    "SUMMARY": "summary",
    "INDEX": "index",
}

client = OpenAI(max_retries=3)


class ChunkEnrichment(BaseModel):
    headline: str
    summary: str


def category(stem: str) -> str:
    return CATEGORY_MAP.get(stem, stem.split("_")[0])


def split_on_headings(text: str, source_file: str, cat: str) -> list[dict]:
    stem = Path(source_file).stem
    heading_re = re.compile(r"^(#{2}) (.+)", re.MULTILINE)
    matches = [(m.start(), len(m.group(1)), m.group(2)) for m in heading_re.finditer(text)]

    if not matches:
        return [{"text": text, "section_heading": stem,
                 "heading_level": 0, "source_file": source_file, "category": cat}]

    chunks = []

    # Keep preamble only if it has content beyond the H1 title and horizontal rules
    preamble = text[: matches[0][0]].strip()
    meaningful = [l for l in preamble.splitlines() if l and not l.startswith("# ") and l.strip() != "---"]
    if meaningful:
        chunks.append({"text": preamble, "section_heading": stem,
                       "heading_level": 0, "source_file": source_file, "category": cat})

    for i, (pos, level, heading_text) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        chunks.append({
            "text": text[pos:end].strip(),
            "section_heading": heading_text,
            "heading_level": level,
            "source_file": source_file,
            "category": cat,
        })

    return chunks


def load_chunks() -> list[dict]:
    chunks = []
    for path in sorted(KB_PATH.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        cat = category(path.stem)
        if path.stem in UNSPLIT:
            chunks.append({"text": text, "section_heading": path.stem,
                           "heading_level": 0, "source_file": path.name, "category": cat})
        else:
            chunks.extend(split_on_headings(text, path.name, cat))
    return chunks


ENRICH_PROMPT = """\
You are indexing a RAG knowledge base representing Alejandro de la Fuente professionally \
(AI engineer, data scientist, quantitative ecologist).

The chunk below is from '{source_file}', section '{section_heading}'.

Write:
- headline: a natural search query or question (under 12 words) that a recruiter or professional \
contact would type to find this content. Write it as a question or search phrase, NOT a document title.
  Good: "What AI frameworks and tools does Alejandro use?"
  Bad: "AI/LLM Skills and Frameworks Overview"
- summary: one sentence, under 20 words, stating the single most useful fact or answer this chunk provides.

Chunk:
{text}
"""


def enrich_chunk(chunk: dict) -> dict:
    prompt = ENRICH_PROMPT.format(
        source_file=chunk["source_file"],
        section_heading=chunk["section_heading"],
        text=chunk["text"][:3000],
    )
    response = client.beta.chat.completions.parse(
        model=ENRICH_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=ChunkEnrichment,
    )
    enrichment = response.choices[0].message.parsed
    return {**chunk, "headline": enrichment.headline, "summary": enrichment.summary}


def enrich_all(chunks: list[dict]) -> list[dict]:
    enriched = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(enrich_chunk, c): i for i, c in enumerate(chunks)}
        for future in tqdm(as_completed(futures), total=len(chunks), desc="Enriching"):
            enriched[futures[future]] = future.result()
    return enriched


def embed(texts: list[str]) -> list[list[float]]:
    # 156 chunks fit in a single call; batching kept for safety if KB grows
    vectors = []
    batch_size = 512
    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding", unit="batch"):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(model=EMBED_MODEL, input=batch)
        vectors.extend(e.embedding for e in response.data)
    return vectors


def store(chunks: list[dict]) -> None:
    chroma = PersistentClient(path=DB_PATH)
    for col in chroma.list_collections():
        if col.name == COLLECTION:
            chroma.delete_collection(COLLECTION)
            break

    collection = chroma.get_or_create_collection(COLLECTION)

    # Embed the enriched representation; the stored document is also the enriched text
    # so the generation LLM receives headline + summary + original_text as context
    documents = [f"{c['headline']}\n\n{c['summary']}\n\n{c['text']}" for c in chunks]
    vectors = embed(documents)
    metadatas = [{k: v for k, v in c.items() if k != "text"} for c in chunks]
    ids = [str(i) for i in range(len(chunks))]

    collection.add(ids=ids, embeddings=vectors, documents=documents, metadatas=metadatas)
    print(f"\nStored {collection.count()} chunks in '{COLLECTION}'")


def print_summary(chunks: list[dict]) -> None:
    by_category: dict[str, int] = {}
    for c in chunks:
        by_category[c["category"]] = by_category.get(c["category"], 0) + 1
    print("Chunks by category:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:<20} {count:>3}")
    unsplit = [c for c in chunks if c["source_file"].split(".")[0] in UNSPLIT]
    print(f"Un-split whole-document chunks: {len(unsplit)}")
    for c in unsplit:
        print(f"  {c['source_file']} ({len(c['text'])} chars)")


if __name__ == "__main__":
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks\n")
    print_summary(chunks)

    print("\nEnriching chunks with headline + summary...")
    enriched = enrich_all(chunks)

    print("\nEmbedding and storing...")
    store(enriched)
    print("\nIngestion complete.")

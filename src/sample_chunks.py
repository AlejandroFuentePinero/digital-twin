"""
Sample and inspect chunks from the ChromaDB knowledge base.

Usage (from repo root):
  uv run src/inspect.py
  uv run src/inspect.py --n 5
  uv run src/inspect.py --n 5 --category research
  uv run src/inspect.py --n 5 --source publications.md
  uv run src/inspect.py --n 5 --seed 42
"""

import argparse
import random
from pathlib import Path

from chromadb import PersistentClient

DB_PATH = str(Path(__file__).parent.parent / "data" / "preprocessed_db")
COLLECTION = "digital_twin"
TEXT_PREVIEW = 500


def sample(n: int, category: str | None, source: str | None, seed: int) -> None:
    chroma = PersistentClient(path=DB_PATH)
    col = chroma.get_collection(COLLECTION)

    where = {}
    if category:
        where["category"] = category
    if source:
        where["source_file"] = source

    result = col.get(
        where=where or None,
        include=["documents", "metadatas"],
    )

    total = len(result["ids"])
    if total == 0:
        print("No chunks matched the filter.")
        return

    random.seed(seed)
    indices = random.sample(range(total), min(n, total))

    print(f"Showing {len(indices)} of {total} chunks\n")

    for rank, i in enumerate(indices, 1):
        meta = result["metadatas"][i]
        doc = result["documents"][i]

        # doc = headline\n\nsummary\n\noriginal_text
        parts = doc.split("\n\n", 2)
        original = parts[2] if len(parts) == 3 else doc

        print(f"{'=' * 70}")
        print(f"[{rank}] {meta['source_file']}  |  {meta['section_heading']}  |  cat:{meta['category']}")
        print(f"HEADLINE : {meta['headline']}")
        print(f"SUMMARY  : {meta['summary']}")
        print(f"TEXT ({len(original.split())} words):")
        print(original[:TEXT_PREVIEW])
        if len(original) > TEXT_PREVIEW:
            print("  [...]")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect KB chunks from ChromaDB")
    parser.add_argument("--n", type=int, default=10, help="Number of chunks to show (default 10)")
    parser.add_argument("--category", type=str, default=None, help="Filter by category")
    parser.add_argument("--source", type=str, default=None, help="Filter by source file (e.g. publications.md)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = parser.parse_args()

    sample(args.n, args.category, args.source, args.seed)

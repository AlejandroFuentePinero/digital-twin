"""One-shot PDF→Markdown extraction for #18 distillation track.

Reads PDFs from data/raw_me/technical_documents/ and writes raw markdown
extracts to data/raw_me/technical_documents/extracted/<key>.md. The extracted
files are intermediate artefacts; the final distilled docs (with locked
Q11 shape — Source link, What it is, Architecture/Methods, Novelty, Results)
land in data/readmes/ via subsequent distillation.

Run:  uv run --with pymupdf4llm python scripts/extract_pdfs.py
"""

from pathlib import Path

import pymupdf4llm

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "data" / "raw_me" / "technical_documents"
OUT = SOURCE / "extracted"

# Map source PDF filename → distilled-doc registry key
PDF_TO_KEY = {
    "Global Change Biology - 2025 - Fuente - Climate‐Induced Physiological Stress Drives Rainforest Mammal Population Declines.pdf": "gcb_2025_physiological_stress",
    "Diversity and Distributions - 2022 - Fuente - Climate change threatens the future of rain forest ringtail possums by 2050.pdf": "dd_2022_ringtail_possums_climate",
    "Diversity and Distributions - 2022 - de la Fuente - Predicted alteration of vertebrate communities in response to.pdf": "dd_2022_vertebrate_communities",
    "delaFuente_mountains_NCC.pdf": "ncc_mountains",
    "delaFuente.et.al.2021.pdf": "delafuente_2021_ecography",
    "Williams_delafuente_2021_plosone.pdf": "williams_delafuente_2021_plosone",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, key in PDF_TO_KEY.items():
        src = SOURCE / filename
        if not src.exists():
            print(f"  MISSING: {filename}")
            continue
        out_path = OUT / f"{key}.md"
        print(f"  {filename}")
        print(f"    → {out_path.relative_to(ROOT)}")
        text = pymupdf4llm.to_markdown(str(src))
        out_path.write_text(text)
        print(f"    {len(text)} chars")
    print(f"\nExtracted {len(PDF_TO_KEY)} PDFs to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()

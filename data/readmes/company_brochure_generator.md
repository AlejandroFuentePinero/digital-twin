# Company Brochure Generator

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/company_sales_brochure_generator

## What it is

A reusable Python utility that turns a company website into a short, readable Markdown brochure using an LLM. Designed for fast prospecting — generating a consistent "who they are / what they do / why they matter" brief for sales, investing, partnership, or recruitment workflows. Markdown output drops cleanly into docs, notes, CRMs, or downstream pipelines.

## Architecture

A minimal **two-stage agentic workflow** — separates "decide what to read" from "write the output." Each stage is a distinct LLM call with a clear intermediate artefact rather than one giant monolithic prompt.

### Stage 1 — Page selection (planning / routing)

- Crawl the homepage, collect candidate links.
- LLM reads the link list and selects a small set of brochure-relevant pages (About, Products, Careers, Customers, etc.).
- Reduces noise vs. scraping everything; the brochure-quality signal is much better when the model only ingests the pages a human would have read.

### Stage 2 — Content synthesis (generation)

- Fetch text content for the homepage + selected pages.
- LLM writes the brochure using the retrieved page text as evidence.
- Output structure (consistent across runs):
  - What the company does and who it serves
  - Products / services and key differentiators (if present)
  - Culture and hiring signals (if present)
- Optionally translate to a target language while preserving Markdown structure.
- Optionally stream tokens during generation in interactive environments.

## Key engineering decisions

- **Two-stage select-then-generate generalises beyond brochures.** The same pattern applies to: marketing copy from website + product pages, investor briefs from public company pages, recruitment briefs from About + Careers pages, internal docs/tutorials from specs + docs pages. The architecture is the contribution; the brochure use case is one specialisation.
- **Page selection as a planning step rather than a heuristic.** Hand-coded "pick pages whose URL contains /about" works in narrow cases; LLM page selection adapts to whatever the company calls their About-equivalent page. The LLM is the heuristic.
- **Markdown without code blocks.** Output drops cleanly into Notion, Confluence, Google Docs, etc. — no escaping needed. Subtle UX choice but matters for actual adoption.
- **Translation as a post-step that preserves structure.** Markdown headers and lists survive the translation pass — the brochure stays usable in the target language.

## Interface

`brochure_generator(company_name, url, model="gpt-4.1-mini", max_pages=6, translate=False, language="Spanish")`

- `company_name` — label used to frame the brochure narrative
- `url` — company homepage to crawl
- `model` — chat model used for both link selection and brochure generation
- `max_pages` — maximum number of relevant pages to fetch in addition to the landing page
- `translate` — if `True`, returns brochure in the requested language
- `language` — target language (e.g., `"Spanish"`, `"French"`)

## Demo

A lightweight Gradio UI demonstrates the utility (local demo; not production hosted).

- Entry point: `./company_sales_brochure_generator/src/app.py`
- Run: `uv run python company_sales_brochure_generator/src/app.py` (requires `OPENAI_API_KEY`)

## Stack

Python · OpenAI · Gradio · BeautifulSoup

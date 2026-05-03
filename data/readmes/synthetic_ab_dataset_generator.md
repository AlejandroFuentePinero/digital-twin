# Synthetic A/B Dataset Generator

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/synthetic_data_generator

## What it is

A lightweight Gradio app that generates a compact synthetic A/B conversion dataset (CSV) plus a Markdown "dataset card" using an LLM. Designed for **quick demo datasets** with a clear schema, controlled treatment effect, and immediately readable documentation — ideal for prototyping dashboards, testing analytics pipelines, teaching experimentation concepts, or building demos where real production data is sensitive, slow to access, or unshareable.

## Architecture

Schema-as-contract generation:

- **Knobs as input** — user specifies dataset size, treatment effect magnitude, allocation ratios, and any custom column constraints.
- **LLM generation under schema contract** — fixed set of columns, allowed values per column, and a binary conversion outcome. The schema is the contract; the LLM fills it.
- **Two output artefacts:**
  - `.csv` — the dataset itself, control + treatment with binary conversion.
  - `_metadata.md` — Markdown dataset card summarising shape, column dictionary, allocation rates, conversion rates, observed lift.
- **Renders dataset card in the UI** for inspection before download.

## Key engineering decisions

- **Schema-as-contract instead of free-form generation.** Standard LLM data generation drifts schemas — a column that should be categorical with three values produces five values across runs. Schema enforcement at the prompt layer guarantees usable output for downstream tooling.
- **Dataset card alongside the data.** A CSV without context is lower-quality than a CSV with a generated description, observed lift, and column dictionary. The card is a cheap addition that dramatically improves dataset usability for the demo/teaching contexts this serves.
- **Both artefacts saved to disk, not just rendered.** Demo datasets get reused; persisting them rather than regenerating means consistent test data across runs and shareable artefacts.

## Demo

Gradio UI demonstrates the generator interactively.

- Entry point: `./synthetic_data_generator/src/ab_data_generator.py`
- Run: `uv run python synthetic_data_generator/src/ab_data_generator.py` (requires `OPENAI_API_KEY`)

## Stack

Python · OpenAI · Gradio · pandas

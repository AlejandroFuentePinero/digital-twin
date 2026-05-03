# Tech Tutor

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/tech_tutor

## What it is

A small, reusable Python utility that answers questions about data work (data engineering, data science, machine learning, software concepts) and explains code in clear Markdown. Designed for fast learning loops: ask a question, paste a snippet, get a memorable explanation you can drop into notes, docs, or study material.

The deliberate twist: a **single movie-based analogy thread** runs through every explanation, configured via the `favourite_movie` parameter. Makes concepts stick without overshooting into fan-fiction.

## Architecture

Single-call utility with multi-backend support.

Given a question (and optionally a code snippet), `tech_tutor(...)`:

- Produces a concise, high-signal explanation aimed at a competent coder new to the specific topic.
- Threads the explanation through a single movie-universe analogy (the `favourite_movie` parameter), with short technical "translations" alongside the analogy to keep the answer rigorous.
- Supports both concept explanations and code walkthroughs (plus practical gotchas).
- Returns Markdown for notes/docs; optionally renders inline in interactive environments.
- Runs via OpenAI (hosted) or Ollama (local) backends from the same interface.

## Key engineering decisions

- **Analogy as backbone, not decoration.** Standard "ELI5"-style explanations sprinkle analogies as garnish; this design makes the analogy the structural spine of the explanation. Technical translations sit alongside, so the rigour isn't lost. The result is faster pattern-recognition for the learner without sacrificing precision.
- **Configurable analogy universe.** `favourite_movie` parameter lets the same tool serve different audiences — kids' fantasy, sci-fi, detective fiction, all work as long as the universe has enough internal structure to support analogies. The parameter is a tone-and-frame contract.
- **Temperature parameter exposed.** `temperature=0.7` default for moderately playful analogies; users tune up for more creativity, down for terse precision.
- **Dual backend (OpenAI + Ollama)** via the same calling interface — same as Web Summary Tool, recurring lab pattern. Hosted for production; local for cost or air-gapped contexts.

## Interface

`tech_tutor(question, code=None, favourite_movie="…", openai_model="…", ollama_model="…", temperature=0.7, show=True, run_open_ai=True, run_ollama=True, ollama_base_url="http://localhost:11434/v1")`

- `question` — concept or code question
- `code` — optional snippet to explain
- `favourite_movie` — analogy-universe selector
- `openai_model` / `ollama_model` — model selection per backend
- `temperature` — creativity dial (higher = more playful analogies)
- `show` — Markdown render vs string return
- `run_open_ai` / `run_ollama` — backend toggles
- `ollama_base_url` — OpenAI-compatible local endpoint

## Demo

Gradio UI demonstrates the tutor interactively (local demo; not production hosted). Supports streaming responses, backend switching, and code-alongside-question input.

- Entry point: `./tech_tutor/src/app.py`
- Run: `uv run python -m tech_tutor.src.app`

## Stack

Python · OpenAI · Ollama · Gradio

# Web Summary Tool

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/ai_web_summary_tool

## What it is

A small, embeddable Python utility that turns a webpage URL into a concise Markdown summary using an LLM. Designed to drop into internal workflows where stakeholders need quick, repeatable briefs from unstructured web content (announcements, reports, research posts) without manual reading.

## Architecture

Single-call pattern with multi-backend support:

- **Fetch and extract** readable text from the webpage URL.
- **Apply safety cap** (`max_chars`, default 25,000) to bound prompt size — crude guardrail against runaway costs and context-length errors.
- **Generate Markdown summary** via a chat model (OpenAI hosted *or* Ollama local, depending on flags).
- **Return or render** based on the `show` flag — return strings for embedding in pipelines, render Markdown for interactive notebooks.

## Key engineering decisions

- **Persona/tone control via parameter.** `chat_personality` adapts the framing to the audience — terse executive brief vs detailed analyst summary, same source content. Useful for one-source-many-audiences workflows.
- **Markdown output by default.** Drops cleanly into docs, notes, CRMs, and downstream pipelines without manual reformatting. Workflow-ready outputs is a recurring discipline across the lab.
- **Dual backend (OpenAI + Ollama) via the same interface.** Hosted API for production reliability; local Ollama for cost control or air-gapped environments. Same calling pattern means switching backends doesn't require code changes upstream.
- **Crude `max_chars` guardrail rather than tokeniser-aware truncation.** Pragmatic — keeps the utility small and dependency-light. Good enough for the use case; tokeniser-aware truncation would be the upgrade if max-chars consistently misfired on edge cases.

## Interface

`web_summary_tool(url, chat_personality="…", openai_model="…", ollama_model="…", max_chars=25000, show=True, run_open_ai=True, run_ollama=True)`

- `url` — webpage to summarise
- `chat_personality` — tone-and-framing parameter passed into the system prompt
- `openai_model` / `ollama_model` — model selection per backend
- `max_chars` — prompt-size guardrail
- `show` — Markdown render vs string return
- `run_open_ai` / `run_ollama` — backend toggles (require `OPENAI_API_KEY` / Ollama installed respectively)

## Stack

Python · OpenAI · Ollama · BeautifulSoup

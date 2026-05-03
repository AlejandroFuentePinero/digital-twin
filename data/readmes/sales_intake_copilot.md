# Sales Intake Copilot

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/sales_chatbot_assistant

## What it is

A lightweight B2B sales-intake chatbot that qualifies a lead in a few turns and produces an internal handoff note for a human sales rep. Demonstrates a business-realistic pattern: **conversational intake on the front end, structured operational artefacts on the back end** — the chatbot serves the user, the structured note serves the downstream sales process.

## Architecture

Conversational loop with structured output discipline:

- **Per user message:** chatbot responds naturally and asks a small number of targeted qualifying questions.
- **Captures key lead attributes:** use case, industry, company size, timeline, budget, decision authority.
- **Produces internal handoff note** in a consistent template so a human SDR/AE can take over without re-asking the same questions.
- **Faithfulness discipline:** avoids inventing details. If the lead didn't state a detail, the note marks it as missing rather than guessing.

## Key engineering decisions

- **Bifurcated output: conversational + structured.** The user sees a natural conversation; the sales team sees a templated note with the same information. Single LLM serves both surfaces, but the prompt contract enforces both shapes — chatty for the user, structured for the rep.
- **No-fabrication discipline.** B2B handoff notes that invent budget or authority cause real damage downstream — the sales rep approaches the lead with wrong assumptions. The system prompt explicitly forbids inferring details that weren't stated.
- **Targeted qualifying questions, not interrogation.** The chatbot picks the next-most-useful question based on what's still missing, rather than running through a fixed checklist. Keeps the conversation natural while still systematically populating the handoff template.

## Interface

`sales_assistant_stream(message, history)`

- `message` — latest user message
- `history` — prior turns in Gradio "messages" format (`[{role, content}, ...]`)
- `model` — chat model used to generate reply + handoff note (currently `gpt-4.1-mini`)

## Demo

Lightweight Gradio UI demonstrates the intake flow (local demo; not production hosted).

- Entry point: `./sales_chatbot_assistant/src/app.py`
- Run: `uv run python -m sales_chatbot_assistant.src.app` (requires `OPENAI_API_KEY`)

## Stack

Python · OpenAI · Gradio

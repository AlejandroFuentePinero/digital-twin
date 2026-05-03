# Flight Booking Agentic Tool

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/price_ticket_agentic_tool

## What it is

A small Gradio app that demonstrates **tool-calling against a real stateful backend**: the assistant can quote return ticket prices from SQLite and create mock bookings with autoincrement booking IDs and departure times. Designed as a minimal but complete agentic pattern — structured tool schemas + a tool router + a multi-step loop that keeps model and tool outputs in sync. Includes voice (TTS) and image generation outputs alongside text.

## Architecture

Tool-calling loop with two registered tools backed by SQLite:

- **`get_ticket_price(destination_city)`** — retrieves prices from a SQLite `prices` table. Deterministic lookup.
- **`book_ticket(destination_city, depart_at?)`** — inserts a new row into a `bookings` table with autoincrement booking ID. Mock state, but real persistence.

Per chat turn the agent:

- Calls `get_ticket_price` to retrieve a quote.
- Asks for explicit confirmation before booking (system-prompt contract).
- Calls `book_ticket` after confirmation, returning a booking ID.
- Returns a one-sentence reply to the user (system-prompt-enforced length).
- Generates a TTS audio version of the reply for autoplay.
- Optionally generates a destination image from the first city referenced in tool calls.

## Key engineering decisions

- **Prompt-as-contract for output discipline.** System prompt enforces *one-sentence answers* and *confirm before booking*. Without the contract, the model rambles or books on first mention. With it, behaviour is predictable across turns.
- **Tool schemas as interfaces.** JSON schemas constrain the model's tool-call arguments (`destination_city`, optional `depart_at`). Schema enforcement at the tool-calling layer means the model can't pass malformed args downstream — defence-in-depth pattern that this Digital Twin's `fetch_project_readme` tool also follows (with `additionalProperties: false`).
- **Tool-call loop discipline.** App executes tool calls, appends both the tool request *and* tool results back into `messages`, and re-calls the model until it returns a final response. Supports multi-step tool usage (price → book → confirm) without manual orchestration.
- **Stateful SQLite backend.** Mock airline data, but real database persistence — booking IDs increment, prices come from a real query. Demonstrates production-shape state handling rather than the in-memory shortcut most tutorials take.
- **Multimodal output (text + audio + image).** Single agent generates three coordinated output modalities. Useful pattern for accessibility (TTS) and engagement (image), without complicating the core tool-calling logic.

## Interface

`booking_agent(history) -> (history, voice_audio_bytes, image)`

- `history` — Gradio "messages" format (`[{role, content}, ...]`)
- `voice_audio_bytes` — TTS audio for autoplay
- `image` — PIL image for the destination (optional)

## Demo

Gradio Blocks UI demonstrates the full chat → tool call → response loop with audio + image outputs.

- Entry point: `./price_ticket_agentic_tool/src/flight_booking_agent.py`
- Run: `uv run python price_ticket_agentic_tool/src/flight_booking_agent.py` (requires `OPENAI_API_KEY`)

## Stack

Python · OpenAI · SQLite · Gradio · OpenAI TTS · OpenAI image generation

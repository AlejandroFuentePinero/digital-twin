# Meeting Minute Generator

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/meeting_minute_audio

## What it is

A Python utility that turns meeting audio into structured Markdown minutes using an LLM. Designed for workflows where meetings happen frequently, recordings exist, and teams need consistent documentation without relying on manual note-taking. Two-stage pipeline: **Whisper transcription → LLM summarisation with faithfulness guardrails**.

## Architecture

Two-stage pipeline:

### Stage 1 — Audio transcription

- Whisper (or compatible ASR) generates a verbatim transcript from the audio recording.
- Transcript persisted to disk for traceability — separates "transcription failed" from "summarisation failed" as distinct debug paths.

### Stage 2 — Structured Markdown summarisation

- LLM reads the transcript and generates Markdown minutes following a fixed structure (the prompt-as-contract):
  - **Summary** — attendees / date / location if stated
  - **Key discussion points** — controlled granularity to avoid bullet-point explosion
  - **Takeaways** — high-level conclusions
  - **Action items** — with owners and due dates if stated
- Missing information explicitly marked as ***Not specified*** rather than guessed or inferred.

Either renders Markdown inline (notebooks) or prints clean output (terminal).

## Key engineering decisions

- **Faithfulness over creativity.** Meeting minutes that invent attendees, action items, or due dates are *worse than nothing* — they create false accountability and confused stakeholders. The system prompt explicitly forbids inferring details that weren't stated; the *Not specified* convention is the honest fallback.
- **Low-temperature generation.** Reduces run-to-run variability for the same recording. Same meeting → roughly the same minutes. Predictability is the operational requirement.
- **Prompt-as-contract for fixed structure.** Every set of minutes has the same sections in the same order. Downstream workflows (calendar sync, action-item tracking, retrospective tooling) can rely on the structure without parsing logic adapting per meeting.
- **Transcript persistence for traceability.** When minutes look wrong, the transcript shows whether the failure was at the ASR layer or the LLM layer. Debugging without persistence is guesswork; with persistence it's a 30-second check.

## Stack

Python · OpenAI Whisper · OpenAI chat models

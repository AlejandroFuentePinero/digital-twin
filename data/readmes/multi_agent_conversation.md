# Multi-Agent Conversation

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/agentic_conversation

## What it is

A small Python project that orchestrates a turn-based, three-agent "review panel" conversation. Each agent plays a business-relevant role: a sceptical Staff Data Scientist (Alex), a pragmatic Product Manager (Blake), and a Tech Lead (Charlie) who synthesises the debate into a shippable plan.

Designed as a learning lab for the **engineering pitfalls of multi-agent systems** — stale context, role drift, duplicated state updates, inconsistent turn-taking — patterns that are easy to miss in demos but break reliability in real use cases (decision reviews, red/blue teaming, structured critique → synthesis pipelines).

## Architecture

Turn-based loop with a single source of truth (the conversation transcript):

- **Initialise shared transcript.** Single conversation state held outside any agent.
- **Per turn:** one agent generates a response from the latest transcript using its role-specific system prompt; response is appended back to the transcript so subsequent turns condition on the evolving dialogue.
- **Repeat for `conversation_length` rounds** (Alex → Blake → Charlie per round).
- **Output:** complete transcript, inspectable, loggable, or adaptable into downstream workflows (e.g., debate → decision memo).

The convergence-toward-action discipline lives in the Tech Lead role's prompt: explicitly responsible for synthesising the debate into actionable next steps rather than continuing to argue.

## Key engineering decisions (the pitfalls this project demonstrates)

- **State is the source of truth.** Each turn must be generated from the latest transcript, not from a frozen prompt string captured at start. This is the most common multi-agent bug — agents drift because they're reasoning about stale context.
- **Prompt contracts.** Each agent's system prompt locks role, tone, and response length to reduce drift over long conversations. Without this, the Staff Data Scientist starts answering as the Product Manager by turn 5.
- **Turn-taking discipline.** One agent speaks at a time; state updates happen exactly once per turn. Avoids the duplicated-update bug where two agents speak in parallel and overwrite each other's contributions.
- **Synthesis as an explicit role.** Charlie's role isn't "be reasonable" — it's "converge to actionable next steps." Without a synthesiser role, multi-agent systems happily debate forever.

## Interface

`agentic_conversation(topic: str, conversation_length: int = 5)`

- `topic` — discussion topic to evaluate in a business context
- `conversation_length` — number of full rounds (Alex → Blake → Charlie) to run

## Code

Entry point: `./agentic_conversation/src/multi-agent-chat.py`

## Stack

Python · OpenAI

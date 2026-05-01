"""Gradio chat interface for the digital twin.

Run:
    uv run src/app.py

Wires the routed pipeline (classifier → branch → retrieval → composer →
generator → guardrail → log) per ADR-0003. Pipeline + its collaborators are
constructed once as a module-level singleton; per-conversation state lives in
Gradio `gr.State` slots.
"""

import sys
import uuid
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).parent))

from branches import REGISTRY
from classifier import Classifier
from composer import PromptComposer
from generator import Generator
from guardrail import Guardrail
from interaction_log import LogWriter
from pipeline import Pipeline
from profile import ProfileLoader

MAX_HISTORY_TURNS = 10  # last N user+assistant pairs passed to the pipeline

# ---------------------------------------------------------------------------
# Module-level singletons (constructed once at import; profile.md read once).
# ---------------------------------------------------------------------------
_profile = ProfileLoader()
_composer = PromptComposer(_profile, REGISTRY)
_pipeline = Pipeline(
    classifier=Classifier(),
    composer=_composer,
    generator=Generator(),
    guardrail=Guardrail(),
    log_writer=LogWriter(),
)


def respond(
    message: str,
    history: list[dict],
    session_id: str,
    turn_count: int,
) -> tuple[str, list[dict], int]:
    """Called on every user submission. Threads turn_count through to the log."""
    chat_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-(MAX_HISTORY_TURNS * 2):]  # each turn = 1 user + 1 assistant msg
    ]
    reply = _pipeline.run(
        question=message,
        history=chat_history,
        session_id=session_id,
        turn_index=turn_count,
    )
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    return "", history, turn_count + 1


def new_session() -> tuple[list, str, int]:
    """Reset conversation, fresh session ID, turn_count back to 0."""
    return [], str(uuid.uuid4()), 0


with gr.Blocks(title="Alejandro de la Fuente — Digital Twin", theme=gr.themes.Soft()) as demo:
    session_id = gr.State(str(uuid.uuid4()))
    history = gr.State([])
    turn_count = gr.State(0)

    gr.Markdown(
        "## Alejandro de la Fuente\n"
        "Ask me anything about Alejandro's professional background — experience, research, "
        "projects, skills, publications, or career trajectory."
    )

    chatbot = gr.Chatbot(
        type="messages",
        label="",
        height=520,
        show_label=False,
        avatar_images=(None, "https://api.dicebear.com/9.x/initials/svg?seed=AF"),
    )

    with gr.Row():
        msg = gr.Textbox(
            placeholder="Ask a question...",
            show_label=False,
            scale=9,
            autofocus=True,
            submit_btn=True,
        )

    with gr.Row():
        clear = gr.Button("New conversation", size="sm", variant="secondary")

    msg.submit(
        respond,
        inputs=[msg, history, session_id, turn_count],
        outputs=[msg, history, turn_count],
    ).then(
        lambda h: h, inputs=[history], outputs=[chatbot]
    )

    clear.click(new_session, outputs=[history, session_id, turn_count]).then(
        lambda h: h, inputs=[history], outputs=[chatbot]
    )


if __name__ == "__main__":
    demo.launch()

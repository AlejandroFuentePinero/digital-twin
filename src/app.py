"""
Gradio chat interface for the digital twin.

Run:
    uv run src/app.py
"""

import uuid
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

MAX_HISTORY_TURNS = 10  # keep last N user+assistant pairs to cap context window

load_dotenv(override=True)

import sys
sys.path.insert(0, str(Path(__file__).parent))
from answer import answer_with_guardrail

def respond(message: str, history: list[dict], session_id: str) -> tuple[str, list[dict]]:
    """Called on every user message. Maintains history in Gradio's messages format."""
    chat_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-(MAX_HISTORY_TURNS * 2):]  # each turn = 1 user + 1 assistant msg
    ]
    reply, _ = answer_with_guardrail(message, chat_history, session_id=session_id)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    return "", history


def new_session() -> tuple[list, str]:
    """Reset conversation and generate a fresh session ID."""
    return [], str(uuid.uuid4())


with gr.Blocks(title="Alejandro de la Fuente — Digital Twin", theme=gr.themes.Soft()) as demo:
    session_id = gr.State(str(uuid.uuid4()))
    history = gr.State([])

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
        inputs=[msg, history, session_id],
        outputs=[msg, history],
    ).then(
        lambda h: h, inputs=[history], outputs=[chatbot]
    )

    clear.click(new_session, outputs=[history, session_id]).then(
        lambda h: h, inputs=[history], outputs=[chatbot]
    )


if __name__ == "__main__":
    demo.launch()

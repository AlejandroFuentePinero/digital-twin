"""Gradio chat interface for the digital twin.

Run:
    uv run src/app.py

Wires the routed pipeline (classifier → branch → retrieval → composer →
generator → guardrail → log) per ADR-0003. Pipeline + its collaborators are
constructed once as a module-level singleton; per-conversation state lives in
Gradio `gr.State` slots.

Per #16: per-session `SessionState` (in `gr.State`) tracks turn count and
contact-provided latch. A collapsible contact-form row appears at the
configured invitation turn (default 3) and persists until the user submits;
on submit, the form writes a `ContactRecord` to `data/logs/contacts.jsonl`
joinable to the interaction log on `session_id`, and `contact_provided` latches
True for the rest of the session.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).parent))

from branches import REGISTRY
from classifier import Classifier
from composer import PromptComposer
from contact_log import ContactRecord, ContactWriter
from generator import Generator
from guardrail import Guardrail
from interaction_log import LogWriter
from pipeline import Pipeline
from profile import ProfileLoader
from rules import GAP_PHRASE
from session_state import (
    INITIAL_FORM_PROMPT,
    SessionState,
    detect_explicit_contact_request,
)
from tools import ToolRegistry, make_litellm_tool_callable

MAX_HISTORY_TURNS = 10  # last N user+assistant pairs passed to the pipeline

# ---------------------------------------------------------------------------
# Module-level singletons (constructed once at import; profile.md read once).
# ToolRegistry hard-fails at startup if data/readmes/registry.json is missing
# or any referenced README file doesn't exist on disk — surfaces deploy issues
# before the first user turn rather than silently breaking on first TECHNICAL probe.
# ---------------------------------------------------------------------------
_profile = ProfileLoader()
_composer = PromptComposer(_profile, REGISTRY)
_tool_registry = ToolRegistry(
    Path(__file__).parent.parent / "data" / "readmes" / "registry.json"
)
_pipeline = Pipeline(
    classifier=Classifier(),
    composer=_composer,
    generator=Generator(),
    guardrail=Guardrail(),
    log_writer=LogWriter(),
    tool_registry=_tool_registry,
    tool_model_callable=make_litellm_tool_callable(),
)
_contact_writer = ContactWriter()


def respond(
    message: str,
    history: list[dict],
    session_id: str,
    state: SessionState,
):
    """Called on every user submission. Increments turn counter, detects contact-flow triggers (explicit request + gap event), threads contact state into the pipeline, and updates form visibility + prompt copy post-turn.

    Three triggers can surface the contact form (Session 26):
      - Turn 3+ (default invitation_turn) — handled by SessionState.should_show_contact_form
      - User explicitly asks to be contacted — detected from message BEFORE Pipeline.run
      - System emits the gap phrase — detected from reply AFTER Pipeline.run

    Form copy switches at turn 7 (re-invitation_turn) per current_form_prompt().
    """
    state.record_turn()
    chat_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-(MAX_HISTORY_TURNS * 2):]  # each turn = 1 user + 1 assistant msg
    ]

    # Trigger detection — explicit request from user message (before generation)
    if detect_explicit_contact_request(message):
        state.mark_explicit_request()

    contact_offered = state.should_show_contact_form()
    reply = _pipeline.run(
        question=message,
        history=chat_history,
        session_id=session_id,
        turn_index=state.turn_counter,
        contact_offered=contact_offered,
        contact_provided=state.contact_provided,
    )

    # Trigger detection — gap event from assistant reply (after generation)
    # Form will appear immediately for the visitor's next view of the page even
    # though this turn's log record may have contact_offered=False (the gap event
    # happened during this turn; offered semantics reflect pre-turn state).
    if GAP_PHRASE in reply:
        state.mark_gap_event()

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    form_visible = gr.update(visible=state.should_show_contact_form())
    form_prompt = gr.update(value=state.current_form_prompt())
    return "", history, state, form_visible, form_prompt


def submit_contact(
    name: str,
    email: str,
    note: str,
    session_id: str,
    state: SessionState,
):
    """Form submit handler. Writes a ContactRecord (joinable to interactions.jsonl on session_id), latches contact_provided=True so the form hides for the rest of the session, and clears the form input values to prevent leakage if the form is somehow re-shown."""
    email_clean = (email or "").strip()
    if not email_clean:
        return (
            gr.update(visible=True),
            gr.update(value="⚠️ Please enter an email address.", visible=True),
            state,
            gr.update(),  # name unchanged on validation error
            gr.update(),  # email unchanged
            gr.update(),  # note unchanged
        )
    try:
        record = ContactRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            turn_index=state.turn_counter,
            name=(name or "").strip() or None,
            email=email_clean,
            note=(note or "").strip() or None,
        )
        _contact_writer.append(record)
        state.mark_contact_provided()
        return (
            gr.update(visible=False),
            gr.update(value="✅ Thanks — Alejandro will be in touch.", visible=True),
            state,
            gr.update(value=""),  # clear name (defence-in-depth — form hidden too)
            gr.update(value=""),  # clear email
            gr.update(value=""),  # clear note
        )
    except Exception as e:
        return (
            gr.update(visible=True),
            gr.update(value=f"⚠️ Submission error: {e}", visible=True),
            state,
            gr.update(),
            gr.update(),
            gr.update(),
        )


def new_session():
    """Reset conversation, fresh session ID, fresh SessionState, hide contact form + status, restore initial form prompt, AND clear form input values.

    The input clearing is a privacy fix — without it, a previous visitor's name/
    email/note persists in the textboxes for the next visitor on the same
    browser session. Surfaced live in Session 26 smoke-test.
    """
    return (
        [],
        str(uuid.uuid4()),
        SessionState(),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=INITIAL_FORM_PROMPT),
        gr.update(value=""),  # clear name input
        gr.update(value=""),  # clear email input
        gr.update(value=""),  # clear note input
    )


with gr.Blocks(title="Alejandro de la Fuente — Digital Twin", theme=gr.themes.Soft()) as demo:
    session_id = gr.State(str(uuid.uuid4()))
    history = gr.State([])
    state = gr.State(SessionState())

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

    # Contact form — hidden by default; becomes visible when any trigger fires
    # (turn 3+, gap event, or explicit user request) and persists until submit
    # or new_session. Wrapped in an Accordion so it's visually separated from
    # the chat area and the user can collapse it. Header copy switches to a
    # re-engagement nudge at turn 7+ via SessionState.current_form_prompt().
    with gr.Accordion("📨 Get in touch", open=True, visible=False) as contact_form:
        contact_prompt = gr.Markdown(INITIAL_FORM_PROMPT)
        with gr.Row():
            contact_name = gr.Textbox(label="Name (optional)", scale=1)
            contact_email = gr.Textbox(label="Email", placeholder="you@example.com", scale=1)
        contact_note = gr.Textbox(
            label="Anything you'd like to share? (optional)",
            lines=2,
            placeholder="Role, project, or anything else worth knowing…",
        )
        with gr.Row():
            contact_submit = gr.Button("Send", variant="primary", size="sm", scale=0)

    contact_status = gr.Markdown(visible=False)

    msg.submit(
        respond,
        inputs=[msg, history, session_id, state],
        outputs=[msg, history, state, contact_form, contact_prompt],
    ).then(
        lambda h: h, inputs=[history], outputs=[chatbot]
    )

    contact_submit.click(
        submit_contact,
        inputs=[contact_name, contact_email, contact_note, session_id, state],
        outputs=[contact_form, contact_status, state, contact_name, contact_email, contact_note],
    )

    clear.click(
        new_session,
        outputs=[
            history, session_id, state,
            contact_form, contact_status, contact_prompt,
            contact_name, contact_email, contact_note,
        ],
    ).then(
        lambda h: h, inputs=[history], outputs=[chatbot]
    )


if __name__ == "__main__":
    demo.launch()

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
from contact_log import ContactRecord, make_contact_writer
from generator import Generator
from guardrail import Guardrail
from hf_log_writer import install_sigterm_handler
from interaction_log import make_log_writer
from pipeline import CANNED_REFUSAL, Pipeline
from profile import ProfileLoader
from rules import GAP_PHRASE
from session_state import (
    INITIAL_FORM_PROMPT,
    SessionState,
    detect_explicit_contact_request,
)
from tools import ToolRegistry, make_litellm_tool_callable

MAX_HISTORY_TURNS = 10  # last N user+assistant pairs passed to the pipeline

# Welcome banner shown above the chat. Recruiters landing on the Space see
# this first; sets expectations for what to ask. Module-level constant so
# tests can verify it renders without inspecting the Blocks tree.
WELCOME_TAGLINE = (
    "Ask me anything about Alejandro's professional background — experience, "
    "research, projects, skills, publications, or career trajectory."
)

# Privacy note rendered as a muted footer line under the chat. Plain-English,
# non-legalistic per the parent PRD (#6); makes the data-flow visible without
# scaring visitors. Email + dataset name are deliberately concrete so a
# deletion request is actionable. Module-level constant so tests can pin the
# wording without scraping rendered HTML.
PRIVACY_NOTE = (
    "Conversations are logged to a private dataset so Alejandro can improve "
    "the system — not publicly visible. Contact "
    "[alejandrofuentepinero@gmail.com](mailto:alejandrofuentepinero@gmail.com) "
    "to request deletion of your session data."
)

# Starter prompts shown as clickable chips above the input. Short label =
# button text; full question = what gets submitted. General-purpose entry
# points spanning research, engineering, and trajectory — let visitors pick
# the angle that matches their interest.
STARTER_PROMPTS: list[tuple[str, str]] = [
    # "Transferable skills" hits the profile.md transfer_principles section
    # (loaded by GENERIC + TECHNICAL): 6 named analytical bridges from
    # quantitative ecology to AI engineering. Use verb "transfer" so the
    # framing matches the source material.
    (
        "Transferable skills",
        "What from your academic research transfers into your AI engineering work?",
    ),
    ("Top AI projects", "What are your top AI projects?"),
    (
        "Impactful research",
        "Provide a summary of your Global Change Biology (2023, 2025) and Nature Climate Change papers.",
    ),
    ("Academic background", "Tell me about your academic background."),
    ("AI background", "Tell me about your background as an AI engineer."),
]

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
_log_writer = make_log_writer()
_pipeline = Pipeline(
    classifier=Classifier(),
    composer=_composer,
    generator=Generator(),
    guardrail=Guardrail(),
    log_writer=_log_writer,
    tool_registry=_tool_registry,
    tool_model_callable=make_litellm_tool_callable(),
)
_contact_writer = make_contact_writer()

# SIGTERM handler — ensures HF Spaces' container-shutdown signal final-
# flushes the buffered writers before the process dies (#47 / #50).
# Variadic so a single signal drains both the interaction-log writer
# and the contact-log writer. Local-backend writers (no `stop` method)
# silently drop out of the drain list. atexit (registered by each
# `make_*_writer`) covers the clean Python-exit path; this covers
# signal-driven termination.
install_sigterm_handler(_log_writer, _contact_writer)


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
        for m in history[
            -(MAX_HISTORY_TURNS * 2) :
        ]  # each turn = 1 user + 1 assistant msg
    ]

    # Trigger detection — explicit request from user message (before generation)
    if detect_explicit_contact_request(message):
        state.mark_explicit_request()

    contact_offered = state.should_show_contact_form()
    # Defence-in-depth — Pipeline.run already catches per-attempt exceptions
    # inside its retry loop and falls back to CANNED_REFUSAL after MAX_ATTEMPTS.
    # This catch covers the rare case where something raises *outside* the loop
    # (classifier, retrieval, composer, log writer) and prevents Gradio from
    # leaving the chat in a hung "spinner forever, no assistant reply" state.
    try:
        reply = _pipeline.run(
            question=message,
            history=chat_history,
            session_id=session_id,
            turn_index=state.turn_counter,
            contact_offered=contact_offered,
            contact_provided=state.contact_provided,
        )
    except Exception as e:
        print(
            f"[app] Pipeline.run raised outside its retry loop: {type(e).__name__}: {e}"
        )
        reply = CANNED_REFUSAL

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


# Theme — neutral grays as the base; the custom CSS file layers the warm-amber
# accent and Inter/JetBrains Mono typography on top. Keeping the theme minimal
# so most styling lives in src/assets/custom.css (one place to edit).
# neutral_hue="gray" is more neutral than "slate" (which has blue undertones
# that bleed through into the chatbot's default surface). custom.css overrides
# the chatbot background separately.
_THEME = gr.themes.Base(
    primary_hue="orange",
    neutral_hue="gray",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "monospace"],
)
_CSS_PATH = Path(__file__).parent / "assets" / "custom.css"
_CUSTOM_CSS = _CSS_PATH.read_text() if _CSS_PATH.exists() else ""

with gr.Blocks(
    title="Alejandro de la Fuente · AI Engineer",
    theme=_THEME,
    css=_CUSTOM_CSS,
) as demo:
    # session_id starts unset; populated per browser session by the
    # demo.load handler below. A literal default like
    # ``str(uuid.uuid4())`` would evaluate once at app boot and be
    # deep-copied to every visitor — distinct visitors then collide on
    # ``(session_id, turn_index)`` and analytics merge them.
    session_id = gr.State()
    history = gr.State([])
    state = gr.State(SessionState())

    # Identity block — monogram, name, role, links. Rendered as raw HTML so the
    # CSS class names in custom.css can target precise structure (a Markdown-
    # rendered version would lose the .identity-monogram / .identity-text split).
    gr.HTML("""
        <div class="identity-block">
          <div class="identity-monogram">AF</div>
          <div class="identity-text">
            <div class="identity-name">Alejandro de la Fuente</div>
            <div class="identity-role">AI Engineer · Melbourne</div>
            <div class="identity-links">
              <a href="https://github.com/AlejandroFuentePinero" target="_blank" rel="noopener">GitHub</a>
              <a href="https://www.linkedin.com/in/alejandro-dela-fuente/" target="_blank" rel="noopener">LinkedIn</a>
              <a href="https://alejandrofuentepinero.github.io/" target="_blank" rel="noopener">Portfolio</a>
            </div>
          </div>
        </div>
        """)

    gr.Markdown(WELCOME_TAGLINE, elem_classes=["tagline-block"])

    # Tips panel — same warm chip palette as the starter prompts so it visually
    # belongs to the same "guidance" surface, distinct from the chat itself.
    gr.HTML("""
        <div class="tips-box">
          <div class="tips-heading">Tips for the best answers</div>
          <ul class="tips-list">
            <li><b>Be specific.</b> <i>"Tell me about Alejandro's RAG project"</i> works better than <i>"Tell me about his work."</i></li>
            <li><b>Start a new conversation when changing topics.</b> Past turns stay in context and can bias later answers — use <b>New conversation</b> below the chat to reset cleanly.</li>
            <li><b>One question at a time.</b> Multi-part questions sometimes get partial answers.</li>
          </ul>
        </div>
        """)

    # "New conversation" — sits above the chat as a small right-aligned text link.
    # Lets visitors reset cleanly when changing topics (per the How-to-use copy).
    with gr.Row(elem_classes=["new-conversation-link"]):
        clear = gr.Button("New conversation", size="sm", variant="secondary")

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

    # Starter prompts — short labels, full question submitted on click.
    # Same handler chain as msg.submit so each click runs the full pipeline turn.
    gr.Markdown("*Or try one of these:*", elem_classes=["tagline-block"])
    with gr.Row(elem_classes=["starter-prompts"]):
        starter_buttons = [
            gr.Button(label, size="sm", variant="secondary")
            for label, _ in STARTER_PROMPTS
        ]

    # Contact form — hidden by default; becomes visible when any trigger fires
    # (turn 3+, gap event, or explicit user request) and persists until submit
    # or new_session. Wrapped in an Accordion so it's visually separated from
    # the chat area and the user can collapse it. Header copy switches to a
    # re-engagement nudge at turn 7+ via SessionState.current_form_prompt().
    with gr.Accordion("📨 Get in touch", open=True, visible=False) as contact_form:
        contact_prompt = gr.Markdown(INITIAL_FORM_PROMPT)
        with gr.Row():
            contact_name = gr.Textbox(label="Name (optional)", scale=1)
            contact_email = gr.Textbox(
                label="Email", placeholder="you@example.com", scale=1
            )
        contact_note = gr.Textbox(
            label="Anything you'd like to share? (optional)",
            lines=2,
            placeholder="Role, project, or anything else worth knowing…",
        )
        with gr.Row():
            contact_submit = gr.Button("Send", variant="primary", size="sm", scale=0)

    contact_status = gr.Markdown(visible=False)

    # Privacy footer — last thing on the page. Muted styling via .privacy-note
    # so it's discoverable without competing with the chat for attention.
    gr.Markdown(PRIVACY_NOTE, elem_classes=["privacy-note"])

    msg.submit(
        respond,
        inputs=[msg, history, session_id, state],
        outputs=[msg, history, state, contact_form, contact_prompt],
    ).then(lambda h: h, inputs=[history], outputs=[chatbot])

    # Starter-prompt wiring — populate msg with the full question, then run the
    # same respond → chatbot chain msg.submit uses. Default-arg captures the
    # question per button (closure over loop variable would otherwise bind all
    # buttons to the last question).
    for btn, prompt in zip(starter_buttons, STARTER_PROMPTS):
        question = prompt[1]
        btn.click(
            lambda q=question: q,
            outputs=[msg],
        ).then(
            respond,
            inputs=[msg, history, session_id, state],
            outputs=[msg, history, state, contact_form, contact_prompt],
        ).then(lambda h: h, inputs=[history], outputs=[chatbot])

    contact_submit.click(
        submit_contact,
        inputs=[contact_name, contact_email, contact_note, session_id, state],
        outputs=[
            contact_form,
            contact_status,
            state,
            contact_name,
            contact_email,
            contact_note,
        ],
    )

    clear.click(
        new_session,
        outputs=[
            history,
            session_id,
            state,
            contact_form,
            contact_status,
            contact_prompt,
            contact_name,
            contact_email,
            contact_note,
        ],
    ).then(lambda h: h, inputs=[history], outputs=[chatbot])

    # Mint a fresh session_id per browser session. ``demo.load`` fires
    # once when each visitor's app first loads, so each visitor's State
    # is initialised with its own UUID. Without this, every visitor's
    # session_id would stay ``None`` until they click "New conversation"
    # (which generates one via ``new_session``), and the interaction
    # log records before that click would all share the same default —
    # collapsing distinct visitors on ``(session_id, turn_index)``.
    demo.load(lambda: str(uuid.uuid4()), inputs=None, outputs=[session_id])


if __name__ == "__main__":
    demo.launch()

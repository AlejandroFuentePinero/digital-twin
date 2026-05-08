"""Smoke tests for `app.py` polish landed in Phase 7 / slice 1 (#51).

`tests/test_session_state.py` already covers the `SessionState` dataclass.
This file pins the *app-level* wiring: the welcome banner + privacy note
constants are present and substantive, and `new_session()` returns a tuple
that resets every state slot the UI threads through `gr.State` (turn
counter + contact_provided + history).
"""

from __future__ import annotations

import app
from session_state import SessionState


def test_welcome_tagline_constant_is_substantive():
    """The welcome banner copy must mention the agent's professional framing
    so a recruiter landing cold knows what to ask."""
    assert app.WELCOME_TAGLINE.strip(), "welcome tagline must not be blank"
    lowered = app.WELCOME_TAGLINE.lower()
    assert "alejandro" in lowered
    assert "professional" in lowered or "background" in lowered


def test_privacy_note_constant_carries_required_signals():
    """Privacy disclosure must name the contact email + the dataset privacy
    stance + a deletion-request affordance, per #51 acceptance."""
    assert app.PRIVACY_NOTE.strip(), "privacy note must not be blank"
    lowered = app.PRIVACY_NOTE.lower()
    assert "alejandrofuentepinero@gmail.com" in lowered
    assert "private" in lowered
    assert "delet" in lowered  # 'deletion' / 'delete' / 'deleted'


def test_new_session_resets_history_session_id_and_session_state():
    """`new_session()` returns the 9-tuple wired into the clear-button outputs.
    The first three slots back the conversation gr.State trio: history (empty
    list), session_id (a fresh UUID-shaped string), and a zeroed SessionState
    (turn_counter=0, contact_provided=False, no latched triggers)."""
    history, session_id, state, *rest = app.new_session()
    assert history == []
    assert isinstance(session_id, str) and len(session_id) >= 32
    assert isinstance(state, SessionState)
    assert state.turn_counter == 0
    assert state.contact_provided is False
    assert state.gap_event_seen is False
    assert state.explicit_request_seen is False
    # The remaining six slots are gr.update() handles for form/status visibility,
    # form copy, and the three input clears. Just assert the count so a refactor
    # that drops a wiring slot fails loudly here.
    assert len(rest) == 6


def test_new_session_returns_distinct_session_ids():
    """Each click of New conversation must mint a fresh UUID — a re-used
    session_id would carry stale interaction-log records into the next session."""
    a = app.new_session()[1]
    b = app.new_session()[1]
    assert a != b


def test_session_id_initial_state_is_unset_and_minted_per_session_via_demo_load():
    """The initial ``session_id`` ``gr.State`` must NOT carry a literal UUID
    default — Gradio deep-copies the default into every session, so a literal
    ``str(uuid.uuid4())`` evaluates once at app boot and ends up shared across
    all visitors until any of them clicks "New conversation". A callable
    default does not help either: ``state_holder.SessionState.__getitem__``
    deep-copies ``block.value`` verbatim and never invokes a callable, so the
    handler would receive the lambda object itself.

    The correct pattern is a ``demo.load`` event that mints a UUID per browser
    session and pipes it into the ``session_id`` State.
    """
    import gradio as gr

    states = [b for b in app.demo.blocks.values() if isinstance(b, gr.State)]
    session_id_states = [s for s in states if s.value is None]
    # Other gr.State slots (history, SessionState) have non-None defaults.
    assert len(session_id_states) >= 1, (
        "session_id gr.State must have a None default — see docstring"
    )

    # demo.load fires per browser session; it should target the session_id
    # State and call a function that returns a UUID-shaped string. Targets
    # are stored as ``(component_id, event_name)`` tuples on each
    # ``BlockFunction``.
    load_fns = [
        d for d in app.demo.fns.values()
        if any(event == "load" for _, event in d.targets)
    ]
    assert load_fns, "demo.load must be registered for per-session session_id minting"

    # Each call to the handler must return a fresh UUID-shaped string —
    # repeated invocations confirm both the shape and the per-session
    # freshness Gradio relies on.
    fn = load_fns[0].fn
    a, b = fn(), fn()
    assert isinstance(a, str) and len(a) >= 32, "load handler must return a UUID string"
    assert a != b, "load handler must return a fresh UUID on each invocation"

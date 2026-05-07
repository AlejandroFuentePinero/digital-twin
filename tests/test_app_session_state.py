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

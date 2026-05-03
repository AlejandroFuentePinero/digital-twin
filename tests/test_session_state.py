from session_state import DEFAULT_INVITATION_TURN, SessionState


def test_initial_state_is_empty():
    """Fresh SessionState — no turns recorded, no contact provided, form hidden."""
    s = SessionState()
    assert s.turn_counter == 0
    assert s.contact_provided is False
    assert s.should_show_contact_form() is False


def test_record_turn_increments_counter():
    """record_turn() bumps turn_counter by exactly one."""
    s = SessionState()
    s.record_turn()
    assert s.turn_counter == 1
    s.record_turn()
    s.record_turn()
    assert s.turn_counter == 3


def test_form_hidden_before_invitation_turn():
    """Form must NOT appear before turn 3 (default invitation_turn)."""
    s = SessionState()
    s.record_turn()
    assert s.should_show_contact_form() is False
    s.record_turn()
    assert s.should_show_contact_form() is False


def test_form_visible_at_invitation_turn():
    """Form becomes visible exactly when turn_counter reaches invitation_turn."""
    s = SessionState()
    for _ in range(DEFAULT_INVITATION_TURN):
        s.record_turn()
    assert s.turn_counter == DEFAULT_INVITATION_TURN
    assert s.should_show_contact_form() is True


def test_form_stays_visible_after_invitation_turn_until_contact_provided():
    """Form persists across turns 4, 5, ... — not a one-shot UI affordance."""
    s = SessionState()
    for _ in range(5):
        s.record_turn()
    assert s.should_show_contact_form() is True
    s.record_turn()
    assert s.should_show_contact_form() is True


def test_mark_contact_provided_latches_and_hides_form_forever():
    """Once user submits the form, contact_provided latches True; form hides for the rest of the session.

    Per #16 acceptance: 'Submit handler sets contact_provided=True and ensures no further
    invitation prompts in that session.'
    """
    s = SessionState()
    for _ in range(5):
        s.record_turn()
    assert s.should_show_contact_form() is True
    s.mark_contact_provided()
    assert s.contact_provided is True
    assert s.should_show_contact_form() is False
    # Subsequent turns must not re-show the form
    for _ in range(10):
        s.record_turn()
    assert s.should_show_contact_form() is False


def test_reset_clears_all_state():
    """reset() — used by new_session() — zeros turn counter and unlatches contact_provided."""
    s = SessionState()
    for _ in range(5):
        s.record_turn()
    s.mark_contact_provided()
    s.reset()
    assert s.turn_counter == 0
    assert s.contact_provided is False
    assert s.should_show_contact_form() is False


def test_invitation_turn_is_configurable():
    """Custom invitation_turn lets tests + future tuning pick a different threshold."""
    s = SessionState(invitation_turn=1)
    assert s.should_show_contact_form() is False
    s.record_turn()
    assert s.should_show_contact_form() is True

import pytest

from session_state import (
    DEFAULT_INVITATION_TURN,
    SessionState,
    detect_explicit_contact_request,
)


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


# ---------------------------------------------------------------------------
# Multi-trigger union (Session 26 expansion):
# - Turn-3 invitation
# - Gap-phrase-triggered (any turn)
# - Explicit-request-triggered (any turn)
# - Turn-7 re-prompt copy change
# All triggers union; contact_provided latches them all off.
# ---------------------------------------------------------------------------


def test_gap_event_triggers_form_visibility_at_any_turn():
    """A gap event surfaces the form immediately, regardless of turn count.

    UX rationale: when the system can't help, "reach out directly" is the
    highest-value bridge — recruiter who asks something off-KB on turn 1
    should see the form NOW, not have to wait until turn 3.
    """
    s = SessionState()
    assert s.should_show_contact_form() is False
    s.record_turn()  # turn 1 — pre-invitation-turn
    assert s.should_show_contact_form() is False
    s.mark_gap_event()
    assert s.should_show_contact_form() is True


def test_explicit_request_triggers_form_visibility_at_any_turn():
    """An explicit recruiter contact request (e.g., 'how can I reach Alejandro?') surfaces the form immediately."""
    s = SessionState()
    s.mark_explicit_request()
    assert s.should_show_contact_form() is True


def test_contact_provided_overrides_all_triggers():
    """Once contact_provided latches True, no trigger combination shows the form."""
    s = SessionState()
    s.mark_gap_event()
    s.mark_explicit_request()
    for _ in range(10):
        s.record_turn()
    assert s.should_show_contact_form() is True
    s.mark_contact_provided()
    # Even with all triggers latched, contact_provided wins
    assert s.should_show_contact_form() is False


def test_reset_clears_gap_and_explicit_request_flags():
    """new_session() must clear the new latches alongside contact_provided + turn_counter."""
    s = SessionState()
    s.mark_gap_event()
    s.mark_explicit_request()
    s.mark_contact_provided()
    s.reset()
    assert s.gap_event_seen is False
    assert s.explicit_request_seen is False
    assert s.contact_provided is False
    assert s.turn_counter == 0
    assert s.should_show_contact_form() is False


def test_form_prompt_changes_at_or_after_re_invitation_turn():
    """Form copy changes at turn 7 (DEFAULT_RE_INVITATION_TURN) — re-engagement nudge per Session 26 design.

    Pre-turn-7: initial copy ('Want a follow-up?'). Turn 7 onwards: re-prompt
    copy ('Still here — happy to be in touch.'). Test by distinctive substring,
    not exact text — wording can evolve.
    """
    from session_state import DEFAULT_RE_INVITATION_TURN
    s = SessionState()
    initial = s.current_form_prompt()
    assert initial != ""
    for _ in range(DEFAULT_RE_INVITATION_TURN - 1):
        s.record_turn()
    assert s.current_form_prompt() == initial, "before re-invitation turn, copy stays initial"
    s.record_turn()  # now turn_counter == DEFAULT_RE_INVITATION_TURN
    re_prompt = s.current_form_prompt()
    assert re_prompt != initial, "at re-invitation turn, copy must change to re-engagement nudge"


# ---------------------------------------------------------------------------
# Explicit-request detector — recruiter-shape contact phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "How can I contact him?",
    "How do I reach Alejandro?",
    "I'd like to get in touch.",
    "Could you reach out to Alejandro for me?",
    "Want to schedule a call with him.",
    "I'd love to speak to Alejandro.",
    "Can you have him contact me?",
    "I want to email you directly.",
    "Set up a call with Alejandro please.",
    "How would I reach out to him?",
])
def test_explicit_request_detector_matches_recruiter_phrases(message):
    """High-precision recruiter-shape phrases trigger the detector."""
    assert detect_explicit_contact_request(message) is True


@pytest.mark.parametrize("message", [
    "What email service does Alejandro use?",      # 'email' alone — false-positive risk
    "Tell me about your work experience.",         # unrelated
    "Have you contacted any major clients?",       # 'contact' as verb but not about reaching Alejandro
    "Can you reach out into the deep learning details?",  # 'reach out' but not contact-me
    "",                                            # empty — defensive
])
def test_explicit_request_detector_no_false_positive(message):
    """Common false-positive shapes (unrelated 'contact'/'email'/'reach' usage) must NOT trigger."""
    assert detect_explicit_contact_request(message) is False

"""Per-session state for #16's contact-flow.

Tracks turn count and contact-provided latch for a single Gradio session.
Held in `gr.State` by `app.py`; extracted into its own module so the state
machine is unit-testable without depending on Gradio.

Lifecycle:
- Fresh session: `turn_counter = 0`, `contact_provided = False`, form hidden.
- Per user turn: `record_turn()` increments counter.
- At `invitation_turn` (default 3): form becomes visible, persists across
  subsequent turns until contact_provided.
- On form submit: `mark_contact_provided()` latches `contact_provided=True`;
  form hides for the rest of the session.
- On `new_session()`: `reset()` zeros all state.
"""

from dataclasses import dataclass

DEFAULT_INVITATION_TURN = 3


@dataclass
class SessionState:
    turn_counter: int = 0
    contact_provided: bool = False
    invitation_turn: int = DEFAULT_INVITATION_TURN

    def record_turn(self) -> None:
        """Call once per completed user-assistant exchange."""
        self.turn_counter += 1

    def should_show_contact_form(self) -> bool:
        """True iff the contact form should be visible to the user right now.

        Becomes True at `invitation_turn`; latches False forever once
        `mark_contact_provided` is called.
        """
        return self.turn_counter >= self.invitation_turn and not self.contact_provided

    def mark_contact_provided(self) -> None:
        """Called by the form submit handler; latches `contact_provided` for this session."""
        self.contact_provided = True

    def reset(self) -> None:
        """Called by `new_session()` — zero turn counter and unlatch contact_provided."""
        self.turn_counter = 0
        self.contact_provided = False

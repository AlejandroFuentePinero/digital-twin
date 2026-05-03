"""Per-session state for #16's contact-flow.

Tracks turn count and contact-flow latches for a single Gradio session. Held
in `gr.State` by `app.py`; extracted into its own module so the state machine
is unit-testable without depending on Gradio.

Three independent triggers can surface the contact form (Session 26 expansion):

1. **Turn-3 invitation** — `turn_counter >= invitation_turn` (default 3).
2. **Gap-event** — system emitted the canonical gap phrase ("I don't have
   that information…") on any turn. Surfaces the form immediately so a
   recruiter who asks something off-KB on turn 1 gets an actionable bridge
   ("reach out directly") instead of a flat dead-end.
3. **Explicit request** — user explicitly asked to be contacted (recruiter
   keyword detection in `app.py`). Latches the form on.

All three triggers union; `contact_provided` (set on form submit) latches them
all off — once the user submits, no trigger combination shows the form again.
`reset()` (called by `new_session()`) clears every latch.

Re-engagement copy: at `re_invitation_turn` (default 7), `current_form_prompt()`
flips from the initial invitation text to a softer "still here" nudge — for
recruiters who saw the form at turn 3 and ignored it.
"""

import re
from dataclasses import dataclass

DEFAULT_INVITATION_TURN = 3
DEFAULT_RE_INVITATION_TURN = 7

# Conservative recruiter-shape phrases for detecting "user explicitly asks to be
# contacted." False negatives are fine (turn-3 invitation covers them eventually);
# false positives are worse (form pops up out of nowhere). Patterns target the
# specific recruiter intent of "I want to reach Alejandro directly," not the
# general appearance of words like "email" or "contact" in unrelated questions
# (e.g. "what email service does he use?").
EXPLICIT_REQUEST_PATTERNS = [
    r"\bcontact\s+(him|alejandro|you)\b",
    r"\breach\s+out\s+to\s+(him|alejandro|you|alejandro\s+directly)\b",
    r"\b(get|getting)\s+in\s+touch\b",
    r"\bin\s+touch\s+with\s+(him|alejandro|you)\b",
    r"\bhow\s+(can|do|should|would)\s+i\s+(contact|reach|email|message)\b",
    r"\bhave\s+(him|alejandro|you)\s+contact\b",
    r"\b(schedule|set\s+up|book)\s+a\s+(call|meeting|chat|conversation)\b",
    r"\b(email|message|call)\s+(him|alejandro|you)\s+directly\b",
    r"\bi('?d|\s+would)\s+(like|love)\s+to\s+(speak|talk|connect)\s+(to|with)\s+(him|alejandro|you)\b",
]
_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in EXPLICIT_REQUEST_PATTERNS]


def detect_explicit_contact_request(message: str) -> bool:
    """True iff the user message contains a recruiter-shape contact-me phrase.

    Conservative by design — see EXPLICIT_REQUEST_PATTERNS comment. Used by
    `app.py::respond()` to surface the contact form immediately when a recruiter
    explicitly asks to be in touch (rather than waiting for the turn-3 invitation).
    """
    if not message:
        return False
    return any(p.search(message) for p in _compiled_patterns)

INITIAL_FORM_PROMPT = "**Want a follow-up?** Drop your details and Alejandro will get in touch directly."
RE_INVITATION_FORM_PROMPT = "**Still here — happy to be in touch.** Drop your details below if useful."


@dataclass
class SessionState:
    turn_counter: int = 0
    contact_provided: bool = False
    gap_event_seen: bool = False
    explicit_request_seen: bool = False
    invitation_turn: int = DEFAULT_INVITATION_TURN
    re_invitation_turn: int = DEFAULT_RE_INVITATION_TURN

    def record_turn(self) -> None:
        """Call once per completed user-assistant exchange."""
        self.turn_counter += 1

    def mark_gap_event(self) -> None:
        """Latch on when the system emits the canonical gap phrase."""
        self.gap_event_seen = True

    def mark_explicit_request(self) -> None:
        """Latch on when the user explicitly asks to be contacted (e.g., 'how can I reach Alejandro?')."""
        self.explicit_request_seen = True

    def should_show_contact_form(self) -> bool:
        """True iff any trigger has fired AND the user has not yet submitted."""
        triggered = (
            self.turn_counter >= self.invitation_turn
            or self.gap_event_seen
            or self.explicit_request_seen
        )
        return triggered and not self.contact_provided

    def current_form_prompt(self) -> str:
        """The form's header text. Switches to a re-engagement nudge at `re_invitation_turn`."""
        if self.turn_counter >= self.re_invitation_turn:
            return RE_INVITATION_FORM_PROMPT
        return INITIAL_FORM_PROMPT

    def mark_contact_provided(self) -> None:
        """Called by the form submit handler; latches `contact_provided` for the rest of this session."""
        self.contact_provided = True

    def reset(self) -> None:
        """Called by `new_session()` — clear every latch and zero the turn counter."""
        self.turn_counter = 0
        self.contact_provided = False
        self.gap_event_seen = False
        self.explicit_request_seen = False

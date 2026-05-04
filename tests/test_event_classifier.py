"""Pure-function tests for the producer-side event-type classifier.

Mirrors the rule in `docs/audits/slice-1-producer-fix.md` — six branches, no
mocks, no I/O. The classifier is the single source of truth for the
`event_type` value the pipeline writes.
"""

from event_classifier import classify_event_type
from rules import DEFLECTION_MARKERS, GAP_PHRASE


def test_returns_refused_when_final_answer_is_none():
    """No accepted attempt → guardrail rejected every retry → refused.

    `final_answer is None` is the strongest signal (no other branch matters);
    the pipeline emits the canned refusal and we record `refused`.
    """
    assert classify_event_type(branch="GENERIC", final_answer=None) == "refused"


def test_returns_gap_for_gap_branch_regardless_of_answer_content():
    """GAP-branch turns are gap by branch policy.

    A constructive gap-aware response (broader-skill reframe, active learning,
    no canonical phrase) is still a gap — the question was a gap question and
    the routing was correct. Branch identity wins over phrase matching.
    """
    assert classify_event_type(
        branch="GAP",
        final_answer="No CUDA work yet, but I have hands-on Modal/HF deploys.",
    ) == "gap"


def test_returns_deflected_for_logistical_branch_regardless_of_answer_content():
    """LOGISTICAL is the deflection branch by design.

    Recruiter-trivia / scheduling / personal-pref questions route to
    LOGISTICAL and the branch policy says deflected. Branch identity wins
    over phrase matching for the same reason GAP does — the routing decision
    encodes the outcome.
    """
    assert classify_event_type(
        branch="LOGISTICAL",
        final_answer="Alejandro is based in Cairns, Australia.",
    ) == "deflected"


def test_returns_gap_when_non_gap_branch_emits_canonical_gap_phrase():
    """A TECHNICAL turn that bottoms out on a missing skill (CUDA, kdb+, …)
    emits the canonical gap phrase. Branch is TECHNICAL but the outcome is a
    gap — the phrase fallback catches it."""
    answer = f"That's a great question. {GAP_PHRASE} Happy to discuss adjacent work."
    assert classify_event_type(branch="TECHNICAL", final_answer=answer) == "gap"


def test_returns_deflected_when_non_logistical_branch_emits_a_deflection_marker():
    """GENERIC out-of-scope (general coding help, trivia) routes to GENERIC
    but the answer is a polite redirect carrying a canonical phrase from the
    DEFLECTION_MARKERS contract. Phrase fallback catches it."""
    # Use the contract literally — picking the first marker is intentional;
    # the contract says "begin redirects with one of these phrases".
    marker = DEFLECTION_MARKERS[0]
    answer = f"{marker} about Alejandro's professional background."
    assert classify_event_type(branch="GENERIC", final_answer=answer) == "deflected"


def test_returns_answered_when_no_branch_or_phrase_rule_fires():
    """The fallback bucket: branch is non-GAP, non-LOGISTICAL; answer is a
    real substantive response — no GAP_PHRASE, no DEFLECTION_MARKERS. This is
    the dominant path on healthy traffic."""
    answer = "Alejandro shipped a Bayesian forecasting paper in Global Change Biology."
    assert classify_event_type(branch="TECHNICAL", final_answer=answer) == "answered"

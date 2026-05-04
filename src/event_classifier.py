"""Producer-side event-type classifier (PRD #41 / issue #42).

Pure function: maps the per-turn `(branch, final_answer)` pair to one of the
four `interaction_log.EventType` values. The pipeline imports this at
log-emit time so the writer carries the same outcome label that the rest of
the system reads — no proxies, no inference downstream.

The rule applies branch identity first (GAP and LOGISTICAL are deflection /
gap by branch policy regardless of phrasing), then falls back to phrase
matching for branches that can produce mixed outcomes (TECHNICAL graceful
gap; GENERIC out-of-scope deflection). See
`docs/audits/slice-1-producer-fix.md` § *Design philosophy* for why
DEFLECTION_MARKERS is a prompt↔producer contract rather than a detector.
"""

from __future__ import annotations

from interaction_log import EventType
from rules import DEFLECTION_MARKERS, GAP_PHRASE


def classify_event_type(branch: str, final_answer: str | None) -> EventType:
    if final_answer is None:
        return "refused"
    if branch == "GAP":
        return "gap"
    if branch == "LOGISTICAL":
        return "deflected"
    if GAP_PHRASE in final_answer:
        return "gap"
    if any(marker in final_answer for marker in DEFLECTION_MARKERS):
        return "deflected"
    return "answered"

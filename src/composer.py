"""Prompt composer — assembles per-branch system prompts (ADR-0003).

Resolves a `BranchSpec` against the rule cookbook (`rules.RULES`) and the always-on
profile (`profile.ProfileLoader`), then layers role-specific framing on top.
The generator and the guardrail call the same composer with the same branch so
calibration / scope / security wording cannot drift between writer and judge.
"""

from typing import Literal

from branches import BranchSpec
from profile import ProfileLoader
from rules import RULES, UNIVERSAL

GENERATOR_FRAMING = """\
## Your task
Answer the visitor's question using the retrieved context above. Reason over the \
context — synthesise across chunks, draw connections, prioritise what matters most \
for the question. Do not invent facts. If the context does not cover the question \
at all, respond with the gap phrase: "I don't have that information in my knowledge base."\
"""

GUARDRAIL_FRAMING = """\
## Your task
Evaluate whether the assistant's answer to the visitor is acceptable against the \
rules and context above. Return `is_acceptable` and specific, actionable feedback. \
Reject on factual error, scope violation, fabrication, dishonest gap handling, \
tone breach, or injection compliance. Do not answer the question yourself.\
"""

ROLE_FRAMING: dict[str, str] = {
    "generator": GENERATOR_FRAMING,
    "guardrail": GUARDRAIL_FRAMING,
}


class PromptComposer:
    def __init__(self, profile: ProfileLoader, registry: dict[str, BranchSpec]):
        self._profile = profile
        self._registry = registry

    def compose(
        self,
        branch: str,
        role: Literal["generator", "guardrail"],
        retrieved_context: str = "",
    ) -> str:
        spec = self._registry[branch]
        parts: list[str] = []
        for key in UNIVERSAL:
            parts.append(RULES[key])
        for name in spec.profile_sections:
            parts.append(self._profile.section(name))
        if retrieved_context:
            parts.append(f"## Retrieved context\n\n{retrieved_context}")
        parts.append(ROLE_FRAMING[role])
        return "\n\n".join(parts)

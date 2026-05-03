"""Branch registry for classify-then-route orchestration (ADR-0003).

Each `BranchSpec` declares which `profile.md` sections to load, the retrieval
`FINAL_K`, the model-callable tools, and the branch-specific rule keys (resolved
later against `rules.RULES`). Today `GENERIC`, `GAP`, `LOGISTICAL`, and
`BEHAVIOURAL` are wired — `TECHNICAL` (#18) lands in a subsequent slice.
"""

from pydantic import BaseModel


class BranchSpec(BaseModel):
    name: str
    profile_sections: list[str]
    final_k: int
    tools: list[str]
    branch_rules: list[str]


REGISTRY: dict[str, BranchSpec] = {
    "GENERIC": BranchSpec(
        name="GENERIC",
        profile_sections=["identity", "narrative_summary", "transfer_principles"],
        final_k=6,
        tools=[],
        branch_rules=["concise_disclosure"],
    ),
    "GAP": BranchSpec(
        name="GAP",
        profile_sections=["identity", "gap_inventory", "active_learning"],
        final_k=6,
        tools=[],
        branch_rules=["calibration_ladder", "concise_disclosure"],
    ),
    "LOGISTICAL": BranchSpec(
        name="LOGISTICAL",
        profile_sections=["identity", "logistics"],
        final_k=6,
        tools=[],
        branch_rules=["concise_disclosure"],
    ),
    "BEHAVIOURAL": BranchSpec(
        name="BEHAVIOURAL",
        profile_sections=["identity", "personal_stories"],
        final_k=6,
        tools=[],
        branch_rules=["deflection", "concise_disclosure"],
    ),
}

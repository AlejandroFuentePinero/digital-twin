"""Canary baseline pointer — frozen golden run_id (issue #39).

A tiny JSON pointer file at ``data/canaries/baseline.json`` names which canary
`run_id` is the frozen golden baseline. The pointer carries metadata
(``frozen_at``, ``frozen_git_sha``, ``notes``) for the canary panel's drift
summary banner. The actual baseline records live in the canonical
``data/logs/interactions.jsonl`` and are recovered by joining on ``run_id``.

Cold-start and stale-pointer behaviour both degrade quietly: missing pointer
→ ``None`` / ``[]``; pointer present but ``run_id`` absent from the log →
``[]``. The canary panel renders 'no baseline frozen' rather than crashing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from interaction_log import InteractionRecord

DEFAULT_BASELINE_PATH = (
    Path(__file__).parent.parent / "data" / "canaries" / "baseline.json"
)


def freeze_baseline(
    run_id: str,
    *,
    frozen_git_sha: str | None = None,
    notes: str = "",
    path: Path = DEFAULT_BASELINE_PATH,
) -> Path:
    """Write a baseline pointer naming ``run_id`` as the frozen golden run.

    `frozen_git_sha` lets the canary panel attribute drift to a specific
    boundary (`from_sha → to_sha`). `notes` is a free-form operator memo
    surfaced in the drift summary banner."""
    payload = {
        "run_id": run_id,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "frozen_git_sha": frozen_git_sha,
        "notes": notes,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def read_baseline(path: Path = DEFAULT_BASELINE_PATH) -> dict | None:
    """Load the baseline pointer; return ``None`` when absent so the canary
    panel can render 'no baseline frozen' instead of crashing."""
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def resolve_baseline_records(
    records: list[InteractionRecord],
    path: Path = DEFAULT_BASELINE_PATH,
) -> list[InteractionRecord]:
    """Subset of ``records`` whose ``run_id`` matches the baseline pointer.

    Returns ``[]`` when the pointer is missing OR when no record shares the
    pointer's ``run_id`` (stale-pointer case). Drift detection short-circuits
    to 'no comparison available' on either branch."""
    pointer = read_baseline(path)
    if pointer is None:
        return []
    target = pointer.get("run_id")
    return [r for r in records if r.run_id == target]

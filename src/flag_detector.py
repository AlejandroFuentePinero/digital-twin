"""Sentinel anomaly flags (issue #34).

Three pure detector functions over `InteractionRecord` lists + cached cluster
files. The Sentinel UI in `sentinel.py` is the only consumer; no I/O inside
the detectors. Each detector emits zero or more `Flag` objects with a target
panel name so clicking a flag in Sentinel can scroll/highlight its drilldown.

The detectors are deliberately conservative: stable / quiet weeks render no
flags. Cold-start (no prior history for `new_cluster`) produces no flags so
the first run establishes the baseline rather than firing on every label.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from dashboard_model import DashboardModel
from interaction_log import InteractionRecord


# Absolute pp jump in gap_rate week-over-week — matches the codebase's
# `wow_delta` convention where fractions are read as percentage points.
FLAG_GAP_RATE_JUMP_THRESHOLD = 0.3
FLAG_REPEAT_FAILURE_COUNT = 3
FLAG_REPEAT_FAILURE_DAYS = 7

FlagTarget = Literal["failure_feed", "gap_clusters", "trend"]


@dataclass(frozen=True)
class Flag:
    """One anomaly surfaced to Sentinel's Flags panel.

    `kind` drives the badge styling and the click-target lookup; `headline` is
    the one-line copy shown to the operator; `detail` is the fuller context
    rendered below the headline; `target` names the panel Sentinel should
    scroll to when the flag is clicked.
    """
    kind: str
    headline: str
    detail: str
    target: FlagTarget


def _trailing_window(records: list[InteractionRecord], *, days: int) -> list[InteractionRecord]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [r for r in records if r.timestamp >= cutoff]


def _prior_window(
    records: list[InteractionRecord], *, days: int
) -> list[InteractionRecord]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=2 * days)).isoformat()
    end = (now - timedelta(days=days)).isoformat()
    return [r for r in records if start <= r.timestamp < end]


def detect_gap_rate_jump(
    records: list[InteractionRecord],
    *,
    threshold: float = FLAG_GAP_RATE_JUMP_THRESHOLD,
    days: int = 7,
) -> list[Flag]:
    """Fire one flag when the trailing-`days` gap rate exceeds the prior
    `days`-window gap rate by more than `threshold` pp."""
    prior_records = _prior_window(records, days=days)
    if not prior_records:
        # No prior-week history → no baseline to compare against. Don't fire on
        # fresh deployments; the next week establishes the baseline.
        return []
    current = DashboardModel(_trailing_window(records, days=days)).gap_rate
    prior = DashboardModel(prior_records).gap_rate
    delta = current - prior
    if delta <= threshold:
        return []
    return [
        Flag(
            kind="gap_rate_jump",
            headline=(
                f"Gap rate jumped {delta * 100:.1f}pp week-over-week "
                f"({prior * 100:.1f}% → {current * 100:.1f}%)"
            ),
            detail=(
                f"Trailing {days}-day window vs prior {days}-day window. "
                "Investigate which questions started failing."
            ),
            target="trend",
        )
    ]


def detect_new_cluster(
    current_clusters: dict | None,
    prior_clusters: list[dict],
) -> list[Flag]:
    """Fire one flag per cluster label in `current_clusters` that doesn't
    appear in any of `prior_clusters`.

    Cold-start safety: empty `prior_clusters` → no flags (the first run
    establishes the baseline). Missing current file (`None`) → no flags
    (matches AC: must not crash when `gap_clusters.json` is absent)."""
    if current_clusters is None or not prior_clusters:
        return []
    historical_labels = {
        c["label"] for prior in prior_clusters for c in prior.get("clusters", [])
    }
    flags: list[Flag] = []
    for cluster in current_clusters.get("clusters", []):
        label = cluster["label"]
        if label in historical_labels:
            continue
        count = cluster.get("count", 0)
        flags.append(
            Flag(
                kind="new_cluster",
                headline=f"New gap cluster: {label}",
                detail=(
                    f"{count} gap question(s) clustered under this label this "
                    "week, with no matching label in any prior weekly cluster file."
                ),
                target="gap_clusters",
            )
        )
    return flags


# Event types that count toward the repeat-failure threshold. Excludes "gap"
# (handled by the new_cluster detector + clustering batch) and "answered"
# (success). Refused + deflected are the operator-actionable repeat patterns.
_REPEAT_FAILURE_EVENTS = {"deflected", "refused"}


def _normalise(question: str) -> str:
    """Case-insensitive + whitespace-trimmed key for question equality."""
    return question.strip().lower()


def detect_repeat_failure(
    records: list[InteractionRecord],
    *,
    count: int = FLAG_REPEAT_FAILURE_COUNT,
    days: int = FLAG_REPEAT_FAILURE_DAYS,
) -> list[Flag]:
    """Fire one flag per question that's been deflected or refused at least
    `count` times within the trailing `days` window."""
    in_window = [
        r for r in _trailing_window(records, days=days)
        if r.event_type in _REPEAT_FAILURE_EVENTS
    ]
    if not in_window:
        return []
    counts: Counter[str] = Counter()
    originals: dict[str, str] = {}
    for r in in_window:
        key = _normalise(r.question)
        counts[key] += 1
        originals.setdefault(key, r.question.strip())
    flags: list[Flag] = []
    for key, n in counts.items():
        if n < count:
            continue
        original = originals[key]
        flags.append(
            Flag(
                kind="repeat_failure",
                headline=(
                    f"Repeated failure ({n}×): {original}"
                ),
                detail=(
                    f"Same question deflected/refused {n} times in the last "
                    f"{days} days. Filter the Failure Feed by this question to "
                    "see every occurrence."
                ),
                target="failure_feed",
            )
        )
    return flags

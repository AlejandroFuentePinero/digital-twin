"""Failure-summarisation batch (issue #33).

Sentinel's Deflection panel reads a cached `data/logs/summaries/deflection_*.md`
written by this module's CLI. The batch runs three groups (unacceptable /
deflection / gap) in one pass via `FailureSummarizer.summarize`; each call is
one LLM round-trip producing a Markdown report.

Sentinel never calls the LLM at page-load — same rationale as
`cluster_gaps.py`. The batch + cached-file split keeps the dashboard fast and
offline-safe.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from litellm import completion
from tenacity import retry, stop_after_attempt, wait_exponential

from failure_feed import classify_failure
from interaction_log import InteractionRecord


DEFAULT_SUMMARIES_DIR = (
    Path(__file__).parent.parent / "data" / "logs" / "summaries"
)


Group = Literal["unacceptable", "deflection", "gap"]

# Writing-quality matters here — these reports get read by a human, not a
# downstream classifier — and the volume is tiny (3 calls per weekly run).
# Per the issue spec.
SUMMARIZER_MODEL = "openai/gpt-4.1"

# Group-specific framing for the user prompt. Keys must match `Group`.
_GROUP_INSTRUCTIONS: dict[Group, str] = {
    "unacceptable": (
        "These turns were rejected by the guardrail at least once. Group them "
        "by the kind of failure (fabrication, scope-creep, tone, calibration, "
        "missed evidence, etc.). For each group: a 1-sentence pattern, 1-2 "
        "verbatim example questions, and a one-line suggestion for what would "
        "have made the answer acceptable. Markdown."
    ),
    "deflection": (
        "These turns triggered the Deflection rule (CONTEXT.md): the system "
        "redirected to live conversation rather than answering. Group them "
        "by topic, surface the questions verbatim where useful, and note "
        "any patterns that suggest the deflection rule could be tightened, "
        "loosened, or extended. Markdown."
    ),
    "gap": (
        "These turns hit the gap phrase ('I don't have that information in "
        "my knowledge base'). Group them by the missing topic, surface the "
        "questions verbatim where useful, and call out any topics that "
        "would be worth adding to the KB or where the broader-skill reframe "
        "in profile.md could plausibly cover the question. Markdown."
    ),
}


_wait = wait_exponential(multiplier=1, min=10, max=120)
_stop = stop_after_attempt(5)


def _empty_placeholder(group: Group, period_days: int) -> str:
    """Mark 'batch ran, no records to summarise' so it's distinguishable from
    'batch never ran' on the dashboard."""
    return (
        f"# {group.capitalize()} summary — last {period_days} days\n\n"
        f"_No {group} records in the last {period_days} days._\n"
    )


def select_records_for_group(
    records: list[InteractionRecord], group: Group, days: int | None
) -> list[InteractionRecord]:
    """Filter records to those matching ``group``'s predicate, in the trailing
    ``days`` window.

    - ``"gap"`` reuses ``failure_feed.classify_failure(r) == "gap"`` so the
      refused-precedence rule is honoured (refused never enters gap).
    """
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        records = [r for r in records if r.timestamp >= cutoff]
    if group == "gap":
        return [r for r in records if classify_failure(r) == "gap"]
    if group == "unacceptable":
        return [
            r for r in records
            if any(not a.get("is_acceptable", True) for a in r.attempts)
        ]
    if group == "deflection":
        return [r for r in records if r.event_type == "deflected"]
    raise NotImplementedError


def _format_record_for_prompt(record: InteractionRecord) -> str:
    """Compact human-readable line for one record. Includes question, branch,
    and the last attempt's answer + guardrail feedback so the summariser has
    enough context to spot patterns without ballooning the prompt."""
    last = record.attempts[-1] if record.attempts else {}
    return (
        f"- **Q:** {record.question}\n"
        f"  **Branch:** {record.branch}  ·  **Event:** {record.event_type}\n"
        f"  **Answer:** {last.get('answer', '')}\n"
        f"  **Guardrail:** {last.get('guardrail_feedback', '')}"
    )


class FailureSummarizer:
    MODEL = SUMMARIZER_MODEL

    @retry(wait=_wait, stop=_stop)
    def summarize(
        self,
        records: list[InteractionRecord],
        group: Group,
        period_days: int,
    ) -> str:
        """One LLM call → Markdown report scoped to ``group``.

        Empty input short-circuits to a 'no records this period' placeholder
        without calling the LLM.
        """
        if not records:
            return _empty_placeholder(group, period_days)
        instructions = _GROUP_INSTRUCTIONS[group]
        body = "\n\n".join(_format_record_for_prompt(r) for r in records)
        user_prompt = (
            f"# Failure group: {group}\n"
            f"# Period: last {period_days} days  ·  {len(records)} records\n\n"
            f"{instructions}\n\n"
            f"## Records\n\n{body}"
        )
        response = completion(
            model=self.MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write concise, recruiter-bar Markdown summaries of "
                        "Digital-Twin failure logs. Patterns over instances. "
                        "Verbatim quotes are fine; speculation is not. Keep it "
                        "scannable."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content


def write_summary(text: str, group: Group, date: str, out_dir: Path) -> Path:
    """Write the summary to ``{out_dir}/{group}_{YYYY-MM-DD}.md`` and return the
    path. Date suffix lets ``latest_summary_path`` sort lexicographically."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{group}_{date}.md"
    path.write_text(text)
    return path


def latest_summary_path(group: Group, summaries_dir: Path) -> Path | None:
    """Most recent `{group}_*.md` in ``summaries_dir`` (None if absent).

    ISO-8601 dates sort lexicographically so plain ``max()`` is enough — no
    datetime parsing needed.
    """
    summaries_dir = Path(summaries_dir)
    if not summaries_dir.exists():
        return None
    matches = list(summaries_dir.glob(f"{group}_*.md"))
    return max(matches) if matches else None


def read_summary(group: Group, summaries_dir: Path) -> str | None:
    """Latest summary text for ``group`` in ``summaries_dir``; None if absent."""
    path = latest_summary_path(group, summaries_dir)
    return path.read_text() if path is not None else None


# Three groups land per run regardless of input volume so the dashboard can
# always answer "is there a recent summary?" with a simple file-exists check.
GROUPS: tuple[Group, ...] = ("unacceptable", "deflection", "gap")


def run_batch(
    *,
    days: int,
    out_dir: Path,
    log_path: Path | None = None,
) -> list[Path]:
    """Read the interaction log, slice it three ways, summarise each group via
    the LLM, and write one date-stamped Markdown file per group. Returns the
    list of paths so the CLI can print them.

    Empty groups skip the LLM and write the no-records placeholder; the file
    is always created so a downstream consumer can rely on three-files-per-run.
    """
    from log_reader import LocalReader

    reader = LocalReader(log_path) if log_path is not None else LocalReader()
    records = reader.read()
    today = datetime.now(timezone.utc).date().isoformat()
    summarizer = FailureSummarizer()

    written: list[Path] = []
    for group in GROUPS:
        group_records = select_records_for_group(records, group=group, days=days)
        text = summarizer.summarize(
            group_records, group=group, period_days=days
        )
        written.append(
            write_summary(text, group=group, date=today, out_dir=out_dir)
        )
    return written


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Summarise the last N days of failure records into 3 Markdown files."
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Trailing window in days (default 7).",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_SUMMARIES_DIR,
        help=f"Output directory (default {DEFAULT_SUMMARIES_DIR}).",
    )
    args = parser.parse_args()
    paths = run_batch(days=args.days, out_dir=args.out_dir)
    for path in paths:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()

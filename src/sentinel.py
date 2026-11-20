"""Sentinel: the operator's page over the interaction log (issue #61 rebuild).

One run reads the log, builds a page model (every figure the page shows,
as plain data) and writes a static page in the calm dashboard style to
``data/logs/sentinel.html`` (gitignored: it quotes visitors' questions),
then opens it. Refresh means running it again; every run reads the log
afresh.

Four tabs, as before the rebuild: Metrics (the Trends split by branch now
sits in each metric's detail window), Canary, Failures, Coverage. A summary
above them says what needs attention and how fresh the log is.

The read is all or nothing: if the dataset listing or any day file fails,
the page says "Log read failed" with the reason and shows no numbers, so a
broken read can never look like a quiet week. Lines that cannot be parsed
and repeated records are counted on the page.

On each run the gap-cluster and deflection-summary caches are rebuilt when
older than ``DEFAULT_FRESHNESS_DAYS``, from the same log the page reads.

Run with ``uv run python src/sentinel.py`` (``--local`` for the local log,
``--no-open`` to skip opening the browser).
"""

from __future__ import annotations

import json
import statistics
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
from dotenv import load_dotenv

matplotlib.use("Agg")  # non-interactive backend — no display needed
from matplotlib.figure import Figure

from cluster_gaps import (
    DEFAULT_ARCHIVE_DIR as CLUSTERS_ARCHIVE_DIR,
    DEFAULT_OUT_PATH as CLUSTERS_DEFAULT_PATH,
    read_cluster_history,
    read_clusters,
)
import cluster_gaps
import canary_runner
import summarize_failures
from canary_baseline import DEFAULT_BASELINE_PATH, resolve_baseline_records
from canary_corpus import DEFAULT_CORPUS_PATH
from canary_verdicts import DEFAULT_VERDICTS_DIR, read_run_verdicts
from contact_log import make_contact_reader, read_provided_session_ids
from dashboard_model import METRIC_GETTERS, DashboardModel
from flag_detector import (
    Flag,
    detect_gap_rate_jump,
    detect_new_cluster,
    detect_repeat_failure,
)
from summarize_failures import DEFAULT_SUMMARIES_DIR, latest_summary_path, read_summary
from failure_feed import FAILURE_MODE_LABELS, classify_failure, tier_for_mode
from failure_feed import _SEVERITY_RANK as _FEED_RANK
from interaction_log import DEFAULT_LOG_PATH, InteractionRecord
from kb_corpus import CoverageEntry, compute_coverage, load_sections
from log_reader import HFLogReader, LocalReader, LogReader, LogReadError, ReadReport, make_log_reader
from metric_status import (
    SHIFT_ALERT,
    SHIFT_WARNING,
    THRESHOLDS,
    metric_status,
    shift_status,
    tier_of,
    wow_delta,
)


# Leftmost column = most recent; all time sits to the right as reference.
WINDOWS = [("7d", 7), ("30d", 30), ("90d", 90), ("Global", None)]
WINDOW_LABELS = ["7 days", "30 days", "90 days", "All time"]

# Cache rebuild cadence for the gap-cluster and deflection-summary batches.
DEFAULT_FRESHNESS_DAYS = 7

# Shift marks (the metrics judged on movement between windows) wait until
# the log spans this many days: before that the windows overlap so much
# that a "shift" is the same data compared with itself.
MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA = 14

CANARY_SPARK_WINDOW = 12
CANARY_SLOW_MULTIPLIER = 1.5  # per-question median latency vs baseline marks it slow
CANARY_FULL_RUN = 150  # 50 questions x 3 answers

PAGE_PATH = DEFAULT_LOG_PATH.parent / "sentinel.html"
TEMPLATE_PATH = Path(__file__).with_name("sentinel_page.html")

BRANCHES = ["GENERIC", "GAP", "TECHNICAL", "BEHAVIOURAL", "LOGISTICAL"]
STAGES = ["total", "classifier", "retrieval", "generation", "guardrail"]
DASH = "–"

CANARY_CATEGORY_LABELS: dict[str, str] = {
    "tool_loop_project": "Project detail via README",
    "branch_routing_technical_named": "Technical, named project",
    "branch_routing_behavioural": "Behavioural",
    "branch_routing_logistical": "Logistical",
    "branch_routing_technical_gap": "Technical gap",
    "branch_routing_gap": "Skill gap",
    "numerical_fidelity": "Numbers",
    "temporal": "Dates",
    "calibration_ladder": "Calibration",
    "personal_story_gated": "Personal story",
    "comparative_spanning": "Comparison across sources",
    "scope_refusal": "Out of scope",
}

COMMANDS = {
    "refresh": "uv run python src/sentinel.py",
    "rebaseline": "uv run python src/canary_runner.py --freeze-baseline",
}


# ---- Readers ----------------------------------------------------------------


class _HFWithLocalCanaryOverlay:
    """Reads live records from an ``HFLogReader`` and overlays the local
    JSONL's canary records.

    ``canary_runner.py`` writes records to ``data/logs/interactions.jsonl``
    regardless of ``DIGITAL_TWIN_LOG_BACKEND``. When Sentinel is pointed at
    the production HF Dataset for live metrics, this wrapper additionally
    reads the local JSONL and surfaces the ``is_canary=True`` records so the
    Canary tab works in the same run as the live tabs.

    The overlay is canary-only: live records on the local file are ignored,
    so they cannot double-count against records already on HF. Its
    ``report`` is the production read's, with any unreadable local line
    added."""

    def __init__(self, primary: HFLogReader, *, local_path=None):
        self._primary = primary
        self._local = LocalReader(local_path or DEFAULT_LOG_PATH)

    def read(self, days: int | None = None) -> list[InteractionRecord]:
        live = self._primary.read(days=days)
        canary = [r for r in self._local.read(days=days) if r.is_canary]
        return live + canary

    @property
    def report(self) -> ReadReport:
        p = self._primary.report
        return ReadReport(
            files_read=p.files_read,
            unreadable_lines=p.unreadable_lines + self._local.report.unreadable_lines,
            duplicates=p.duplicates,
        )


def _wrap_with_canary_overlay_if_hf(reader: LogReader) -> LogReader:
    """If ``reader`` is an ``HFLogReader``, wrap it with
    ``_HFWithLocalCanaryOverlay`` so the local canary records overlay onto
    the HF live records. Pass-through for any other reader."""
    if isinstance(reader, HFLogReader):
        return _HFWithLocalCanaryOverlay(reader)
    return reader


def _default_reader() -> LogReader:
    """``HF_TOKEN`` + ``HF_DATASET_REPO`` set → production (``HFLogReader``
    with the local canary overlay); otherwise the local log."""
    return _wrap_with_canary_overlay_if_hf(make_log_reader())


def _production_reader(reader: LogReader) -> HFLogReader | None:
    if isinstance(reader, _HFWithLocalCanaryOverlay):
        return reader._primary
    if isinstance(reader, HFLogReader):
        return reader
    return None


# ---- Formatters --------------------------------------------------------------


def _fmt_pct(rate: float | None) -> str:
    return DASH if rate is None else f"{rate * 100:.1f}%"


def _fmt_seconds(ms: float | None) -> str:
    return DASH if ms is None else f"{ms / 1000:.2f} s"


_fmt_ms = _fmt_seconds


def _fmt_num(n: float | None, ndigits: int = 1) -> str:
    return DASH if n is None else f"{n:.{ndigits}f}"


def _short_sha(sha: str | None) -> str:
    return sha[:7] if sha else DASH


# ---- Metric definitions -------------------------------------------------------


# Each row: (display label, metric name or None, getter, formatter). A row with
# no metric name is for orientation only: it never carries a mark.
METRIC_SPECS: list[tuple[str, list[tuple]]] = [
    ("Outcome", [
        ("Total interactions",         None,                          lambda m: m.total_interactions, str),
        ("Answered with substance",    "answered_with_substance_rate", lambda m: m.answered_with_substance_rate, _fmt_pct),
        ("Gap rate",                   "gap_rate",                    lambda m: m.gap_rate, _fmt_pct),
        ("Deflection rate",            "deflection_rate",             lambda m: m.deflection_rate, _fmt_pct),
        ("Refusal rate",               "refusal_rate",                lambda m: m.refusal_rate, _fmt_pct),
        ("Guardrail rejection rate",   "guardrail_rejection_rate",    lambda m: m.guardrail_rejection_rate, _fmt_pct),
        ("Retry-exhaustion rate",      "retry_exhausted_rate",        lambda m: m.retry_exhausted_rate, _fmt_pct),
        ("Attempts distribution",      None,                          lambda m: m.attempts_distribution, None),
    ]),
    ("Routing", [
        ("Classifier branch distribution",         None,                          lambda m: m.branch_distribution, None),
        ("Classifier mean confidence",             "mean_classification_confidence", lambda m: m.mean_classification_confidence, lambda v: _fmt_num(v, 2)),
        ("Classifier mean confidence by branch",   None,                          lambda m: m.mean_confidence_by_branch, None),
        ("Classifier low-confidence rate (<0.7)",  "low_confidence_rate",         lambda m: m.low_confidence_rate(), _fmt_pct),
    ]),
    ("Engagement", [
        ("Unique sessions",            None,                          lambda m: m.unique_sessions, str),
        ("Avg questions per session",  "mean_turns_per_session",      lambda m: m.mean_turns_per_session, lambda v: _fmt_num(v, 2)),
        ("Turns/session (median)",     "turns_per_session_median",    lambda m: m.turns_per_session_median, _fmt_num),
        ("Contact-offer rate",         "contact_offer_rate",          lambda m: m.contact_offer_rate, _fmt_pct),
        ("Contact-conversion rate",    "contact_conversion_rate",     lambda m: m.contact_conversion_rate, _fmt_pct),
    ]),
    ("Tool use", [
        ("Tool calls (count)",         None,                          lambda m: m.tool_call_count, str),
        ("Tool calls by branch",       None,                          lambda m: m.tool_calls_by_branch, None),
        ("Tool-call success rate",     "tool_call_success_rate",      lambda m: m.tool_call_success_rate, _fmt_pct),
    ]),
    ("Latency", [
        ("classifier",                 None,                          lambda m: m.latency_with_share("classifier"), None),
        ("retrieval",                  None,                          lambda m: m.latency_with_share("retrieval"), None),
        ("generation",                 None,                          lambda m: m.latency_with_share("generation"), None),
        ("guardrail",                  None,                          lambda m: m.latency_with_share("guardrail"), None),
        ("total (p95)",                "latency_p95_total",           lambda m: m.latency_percentiles("total").get(95), _fmt_ms),
    ]),
]

# What each row measures, shown in its detail window. Keys match the labels
# in METRIC_SPECS exactly (a test pins the two together).
METRIC_GLOSSARY: dict[str, str] = {
    "Total interactions": "Every logged turn in the window, deploy checks included.",
    "Answered with substance": "Share of turns logged as answered. Not yet trustworthy: the twin sets this label from the branch that handled the question, not from reading the answer (#63).",
    "Gap rate": "Share of turns logged as a gap: the twin said it did not have the information, or answered on the gap branch. Not yet trustworthy: the label follows the branch, not the answer (#63).",
    "Deflection rate": "Share of turns logged as deflected: the twin redirected a question it treats as out of scope, or answered on the logistical branch. Not yet trustworthy: the label follows the branch, not the answer (#63).",
    "Refusal rate": "Share of turns that ended in the canned refusal: the guardrail rejected all three attempts, or the classifier, retrieval or composer failed before the first attempt.",
    "Guardrail rejection rate": "Share of turns where the guardrail rejected at least one attempt.",
    "Retry-exhaustion rate": "Share of turns that used all three attempts, whether or not the last one was accepted.",
    "Attempts distribution": "Share of turns by how many attempts they took: one, two or three.",
    "Classifier branch distribution": "Share of turns the classifier sent to each branch.",
    "Classifier mean confidence": "The classifier's average confidence in the branch it chose.",
    "Classifier mean confidence by branch": "The classifier's average confidence, for each branch it chose.",
    "Classifier low-confidence rate (<0.7)": "Share of turns where the classifier's confidence was below 0.7.",
    "Unique sessions": "Distinct conversations in the window.",
    "Avg questions per session": "Turns per conversation, on average.",
    "Turns/session (median)": "Turns in the typical conversation.",
    "Contact-offer rate": "Share of turns where the contact form was on offer.",
    "Contact-conversion rate": "Share of conversations offered the contact form that submitted it, matched against the contact submissions.",
    "Tool calls (count)": "README fetches the twin made in the window.",
    "Tool calls by branch": "Where the README fetches happened: each branch's share of the turns that fetched one.",
    "Tool-call success rate": "Share of README fetches that returned the file.",
    "classifier": "Time in the classifier stage: the slowest 5% of turns (p95), the typical turn (p50), and the stage's share of the whole turn's p95.",
    "retrieval": "Time in the retrieval stage: the slowest 5% of turns (p95), the typical turn (p50), and the stage's share of the whole turn's p95.",
    "generation": "Time in the answer-writing stage: the slowest 5% of turns (p95), the typical turn (p50), and the stage's share of the whole turn's p95.",
    "guardrail": "Time in the guardrail stage: the slowest 5% of turns (p95), the typical turn (p50), and the stage's share of the whole turn's p95.",
    "total (p95)": "Time for the whole turn, for the slowest 5% of turns.",
}

# The metrics whose Trends split by branch now sits in the Metrics detail window.
THEMATIC_BLOCKS: dict[str, list[str]] = {
    "Outcome": [
        "answered_with_substance_rate", "gap_rate", "deflection_rate",
        "refusal_rate", "guardrail_rejection_rate", "retry_exhausted_rate",
    ],
    "Routing": ["mean_classification_confidence", "low_confidence_rate"],
    "Engagement": [
        "mean_turns_per_session", "turns_per_session_median",
        "contact_offer_rate", "contact_conversion_rate",
    ],
    "Tool use": ["tool_call_success_rate"],
    "Latency": ["latency_p95_total"],
}

METRIC_UNITS: dict[str, str] = {
    "gap_rate": "pp", "deflection_rate": "pp", "refusal_rate": "pp",
    "guardrail_rejection_rate": "pp", "retry_exhausted_rate": "pp",
    "answered_with_substance_rate": "pp", "low_confidence_rate": "pp",
    "tool_call_success_rate": "pp", "contact_conversion_rate": "pp",
    "contact_offer_rate": "pp", "latency_p95_total": "ms",
    "mean_classification_confidence": "", "turns_per_session_median": "",
    "mean_turns_per_session": "",
}


def _fmt_metric_value(metric: str, value: float | None) -> str:
    unit = METRIC_UNITS.get(metric, "")
    if unit == "pp":
        return _fmt_pct(value)
    if unit == "ms":
        return _fmt_seconds(value)
    return _fmt_num(value)


def _mark_rule(metric: str | None) -> str:
    """The rule behind a row's mark, in plain words."""
    if metric is None or tier_of(metric) == "C":
        return "Not marked: it describes the system rather than judging it."
    if tier_of(metric) == "B":
        return (
            f"Judged on movement: a warning when it moves {SHIFT_WARNING:.0%} or more "
            f"between the 7- and 30-day or the 30- and 90-day windows, an alert at "
            f"{SHIFT_ALERT:.0%}. Not marked until the log spans "
            f"{MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA} days."
        )
    t = THRESHOLDS[metric]
    fmt = _fmt_seconds if t.unit == "ms" else (lambda v: f"{v * 100:g}%")
    if t.higher_is_better:
        return (f"Judged on its value: healthy at {fmt(t.healthy)} or more, a warning "
                f"down to {fmt(t.warning)}, an alert below.")
    return (f"Judged on its value: healthy at {fmt(t.healthy)} or less, a warning "
            f"up to {fmt(t.warning)}, an alert above.")


# ---- Status rules --------------------------------------------------------------


def _status_class(metric_name: str | None, value: float | None) -> str:
    """Mark for one value cell: only metrics judged on their value carry one."""
    if metric_name is None or tier_of(metric_name) != "A":
        return ""
    return metric_status(metric_name, value) or ""


def _data_history_days(records: list[InteractionRecord]) -> int:
    """Days spanned by the record set (latest date minus earliest date)."""
    if not records:
        return 0
    timestamps = [r.timestamp for r in records]
    try:
        d_early = datetime.fromisoformat(min(timestamps)[:10]).date()
        d_late = datetime.fromisoformat(max(timestamps)[:10]).date()
    except ValueError:
        return 0
    return (d_late - d_early).days


def _worst_status(statuses: list[str | None]) -> str | None:
    s = [x for x in statuses if x is not None]
    if not s:
        return None
    if "alert" in s:
        return "alert"
    if "warning" in s:
        return "warning"
    return "healthy"


def _row_severity(metric_name: str | None, raws: list, history_days: int = 0) -> str:
    """Worst status of a row: value bands over every window for metrics
    judged on value; movement 7d↔30d and 30d↔90d for metrics judged on
    movement (only once the log spans MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA
    days); "orientation" for the rest."""
    if metric_name is None:
        return "orientation"
    t = tier_of(metric_name)
    if t == "A":
        return _worst_status([metric_status(metric_name, v) for v in raws]) or "orientation"
    if t == "B":
        if len(raws) < 3 or history_days < MIN_HISTORY_DAYS_FOR_SEMANTIC_DELTA:
            return "orientation"
        return _worst_status([shift_status(raws[0], raws[1]), shift_status(raws[1], raws[2])]) or "orientation"
    return "orientation"


_SEVERITY_RANK = {"alert": 0, "warning": 1, "orientation": 2, "healthy": 3}


# ---- Cached cluster and summary batches -------------------------------------------


def is_stale(path: Path, max_age_days: int = DEFAULT_FRESHNESS_DAYS) -> bool:
    """True when ``path`` is missing or older than ``max_age_days``."""
    path = Path(path)
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime < datetime.now(timezone.utc) - timedelta(days=max_age_days)


def _run_with_capture(label: str, fn) -> str | None:
    try:
        fn()
        return None
    except Exception as exc:
        # A retried call fails as tenacity's RetryError, whose text hides the
        # cause; report the last attempt's exception instead.
        last = getattr(exc, "last_attempt", None)
        cause = last.exception() if last is not None and last.exception() is not None else exc
        return f"{label} batch failed: {type(cause).__name__}: {cause}"


def ensure_fresh_clusters(
    log_path: Path | None = None,
    out_path: Path = CLUSTERS_DEFAULT_PATH,
    archive_dir: Path | None = CLUSTERS_ARCHIVE_DIR,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
    *,
    reader: LogReader | None = None,
) -> str | None:
    if not is_stale(out_path, max_age_days):
        return None
    return _run_with_capture(
        "Cluster",
        lambda: cluster_gaps.run_batch(
            days=cluster_gaps.BATCH_DEFAULT_DAYS,
            out_path=out_path,
            log_path=log_path,
            archive_dir=archive_dir,
            reader=reader,
        ),
    )


def ensure_fresh_summaries(
    log_path: Path | None = None,
    out_dir: Path = DEFAULT_SUMMARIES_DIR,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
    *,
    reader: LogReader | None = None,
) -> str | None:
    latest = latest_summary_path("deflection", out_dir)
    if latest is not None and not is_stale(latest, max_age_days):
        return None
    return _run_with_capture(
        "Summary",
        lambda: summarize_failures.run_batch(
            days=summarize_failures.BATCH_DEFAULT_DAYS,
            out_dir=out_dir,
            log_path=log_path,
            reader=reader,
        ),
    )


def _latest_canary_timestamp(records: list[InteractionRecord]) -> str | None:
    canary = [r for r in records if r.is_canary]
    if not canary:
        return None
    return max(r.timestamp for r in canary)


def ensure_fresh_canaries(
    reader: LogReader | None = None,
    *,
    max_age_days: int = DEFAULT_FRESHNESS_DAYS,
    runner: callable = canary_runner.run_batch,
) -> str | None:
    """Run the canary batch when the most recent canary run is older than
    ``max_age_days`` (or absent); failures come back as a message."""
    reader = reader or _default_reader()
    latest = _latest_canary_timestamp(reader.read())
    if latest is not None:
        latest_dt = datetime.fromisoformat(latest)
        if latest_dt > datetime.now(timezone.utc) - timedelta(days=max_age_days):
            return None
    return _run_with_capture("Canary", lambda: runner())


def _canary_runs_grouped(
    records: list[InteractionRecord],
) -> list[tuple[str, list[InteractionRecord]]]:
    """Canary records grouped by ``run_id``, oldest run first."""
    canary = [r for r in records if r.is_canary and r.run_id]
    by_run: dict[str, list[InteractionRecord]] = {}
    for r in canary:
        by_run.setdefault(r.run_id, []).append(r)
    return sorted(by_run.items(), key=lambda kv: min(r.timestamp for r in kv[1]))


def canary_metric_history(
    records: list[InteractionRecord],
    metric: str,
    *,
    last_n: int = CANARY_SPARK_WINDOW,
) -> list[float | None]:
    """One value per canary run for ``metric``, oldest-first, capped to the
    last ``last_n`` runs."""
    getter = METRIC_GETTERS.get(metric)
    if getter is None:
        return []
    runs = _canary_runs_grouped(records)[-last_n:]
    return [
        getter(DashboardModel(rs, include_canary=True, only_canary=True))
        for _, rs in runs
    ]


def render_sparkline(
    values: list[float | None],
    baseline: float | None,
) -> Figure | None:
    """Tiny matplotlib sparkline: line over ``values`` with a horizontal
    reference line at ``baseline``. ``None`` when there's nothing to draw."""
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return None
    fig = Figure(figsize=(1.6, 0.32), dpi=150)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("#1c1c20")
    ax.set_facecolor("#1c1c20")
    xs = list(range(len(values)))
    ys = [v if v is not None else float("nan") for v in values]
    ax.plot(xs, ys, color="#9ca3af", linewidth=1.0)
    if baseline is not None:
        ax.axhline(baseline, color="#5a5a64", linewidth=0.6, linestyle="--", alpha=0.9)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig


# ---- Page model -------------------------------------------------------------------


def _iso(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(timezone.utc).isoformat()


def _structured_cell(raw, label: str) -> dict | None:
    """Latency and distribution cells as structured data; None for scalars."""
    if raw is None:
        return {"kind": "text", "text": DASH}
    if isinstance(raw, dict) and {"p50", "p95"} <= set(raw):
        share = raw.get("share")
        return {"kind": "latency", "p50": _fmt_seconds(raw.get("p50")),
                "p95": _fmt_seconds(raw.get("p95")),
                "share": DASH if share is None else f"{share * 100:.0f}%"}
    if isinstance(raw, dict):
        if not raw:
            return {"kind": "text", "text": DASH}
        if "branch" in label.lower():
            items = sorted(raw.items(), key=lambda kv: -kv[1])
            return {"kind": "dist", "items": [[str(k).capitalize(), f"{v * 100:.0f}%"] for k, v in items]}
        return {"kind": "dist", "items": [[f"Attempt {k}", f"{v * 100:.0f}%"] for k, v in raw.items()]}
    return None


def _metrics_section(model: DashboardModel) -> tuple[list[dict], list[int]]:
    models = [model.for_window(days=d) for _, d in WINDOWS]
    # All time has no earlier window to compare with, so it gets no prior.
    priors = [model.for_prior_window(days=d) if d is not None else None for _, d in WINDOWS]
    history_days = _data_history_days(models[-1].records)
    trend_metrics = {m for ms in THEMATIC_BLOCKS.values() for m in ms}
    sections = []
    for name, specs in METRIC_SPECS:
        rows = []
        for label, metric, getter, fmt in specs:
            raws = [getter(m) for m in models]
            severity = _row_severity(metric, raws, history_days=history_days)
            cells = []
            for i, raw in enumerate(raws):
                cell = _structured_cell(raw, label)
                if cell is None:
                    cell = {"kind": "text", "text": fmt(raw) if fmt is not str else str(raw)}
                cell["status"] = _status_class(metric, raw)
                prior = getter(priors[i]) if (metric and priors[i] is not None) else None
                d = wow_delta(metric, raw, prior) if metric else None
                if d is not None and d.direction != "stable":
                    mag = (f"{abs(d.delta) * 100:.1f} pp" if d.unit == "pp"
                           else f"{abs(d.delta) / 1000:.2f} s" if d.unit == "ms"
                           else f"{abs(d.delta):.2f}")
                    cell["delta"] = ("+" if d.delta > 0 else "−") + mag
                cells.append(cell)
            by_branch = None
            if metric in trend_metrics:
                by_branch = []
                for b in BRANCHES:
                    values = []
                    for wm in models:
                        recs = [r for r in wm.records if r.branch == b]
                        v = METRIC_GETTERS[metric](
                            DashboardModel(recs, provided_session_ids=model.provided_session_ids)
                        ) if recs else None
                        values.append({"text": _fmt_metric_value(metric, v), "n": len(recs)})
                    by_branch.append({"branch": b.capitalize(), "values": values})
            rows.append({"label": label, "severity": severity, "cells": cells,
                         "about": METRIC_GLOSSARY.get(label, ""), "rule": _mark_rule(metric),
                         "by_branch": by_branch})
        rows.sort(key=lambda r: _SEVERITY_RANK.get(r["severity"], 9))
        sections.append({"name": name, "rows": rows})
    return sections, [m.total_interactions for m in models]


def _failures_section(live: list[InteractionRecord]) -> list[dict]:
    sessions: dict[str, list[InteractionRecord]] = {}
    for r in live:
        sessions.setdefault(r.session_id, []).append(r)
    rows = []
    for r in live:
        mode = classify_failure(r)
        if mode is None:
            continue
        turns = sorted(sessions[r.session_id], key=lambda x: (x.turn_index, x.timestamp))
        rows.append({
            "ts": _iso(r.timestamp), "branch": r.branch.capitalize(), "mode": mode,
            "tier": tier_for_mode(mode), "question": r.question,
            "labels": list(r.classifier_labels or []), "confidence": r.classification_confidence,
            "event": r.event_type,
            "error": f"{r.failed_stage}: {r.error_type}: {r.error_message}" if r.failed_stage else None,
            "attempts": [{"ok": a.get("is_acceptable", True), "answer": a.get("answer", ""),
                          "feedback": a.get("guardrail_feedback", "")} for a in r.attempts],
            "chunks": [f"{c.get('source_file', '')} · {c.get('section_heading', '')}" for c in r.retrieved_chunks],
            "tools": [f"{c.get('name', '')} · {c.get('status', '')}" for c in (r.tool_calls or [])],
            "latency": {k: r.latency_ms.get(k, 0) for k in STAGES},
            "session": [{"turn": t.turn_index, "question": t.question,
                         "mode": classify_failure(t) or "answered", "self": t is r} for t in turns],
        })
    # Sentinel's feed order: the worst kind first, newest first within a kind.
    rows.sort(key=lambda x: x["ts"], reverse=True)
    rows.sort(key=lambda x: _FEED_RANK.get(x["mode"], 99))
    return rows


def _median_total_ms(records: list[InteractionRecord]) -> dict[str, float]:
    by_q: dict[str, list[float]] = {}
    for r in records:
        by_q.setdefault(r.question, []).append(r.latency_ms.get("total", 0))
    return {q: statistics.median(v) for q, v in by_q.items()}


def _canary_section(
    all_records: list[InteractionRecord], *, verdicts_dir: Path, baseline_path: Path, corpus_path: Path,
) -> dict | None:
    """Every canary run since the frozen baseline, and the latest run's
    questions with their verdicts, answers and categories."""
    runs = _canary_runs_grouped(all_records)
    if not runs:
        return None
    canary_only = [r for r in all_records if r.is_canary]
    baseline_records = resolve_baseline_records(canary_only, baseline_path)
    base_id = json.loads(Path(baseline_path).read_text())["run_id"] if Path(baseline_path).exists() else None
    corpus = {q["id"]: q for q in json.loads(Path(corpus_path).read_text())} if Path(corpus_path).exists() else {}
    ids = [rid for rid, _ in runs]
    start = ids.index(base_id) if base_id in ids else len(ids) - 1
    run_rows = []
    for rid, recs in runs[start:]:
        m = DashboardModel(recs, include_canary=True, only_canary=True)
        v = read_run_verdicts(rid, verdicts_dir)
        per_q = _median_total_ms(recs)
        run_rows.append({
            "id": rid, "ts": _iso(min(r.timestamp for r in recs)), "sha": _short_sha(recs[0].git_sha),
            "records": len(recs), "full": CANARY_FULL_RUN, "baseline": rid == base_id,
            "q_pass": sum(x.passed for x in v) if v else None, "q_n": len(v) if v else None,
            "r_pass": sum(rr.passed for x in v for rr in x.replicates) if v else None,
            "r_n": sum(len(x.replicates) for x in v) if v else None,
            "median": _fmt_seconds(statistics.median(per_q.values())) if per_q else DASH,
            "p95": {s: _fmt_seconds(m.latency_percentiles(s).get(95)) for s in STAGES},
        })
    latest_id, latest = runs[-1]
    verdicts = read_run_verdicts(latest_id, verdicts_dir) or []
    cur_ms, base_ms = _median_total_ms(latest), _median_total_ms(baseline_records)
    rec_by = {(r.question, r.replicate_index): r for r in latest}
    questions = []
    for v in sorted(verdicts, key=lambda v: (v.passed, v.question_id)):
        cur, base = cur_ms.get(v.question), base_ms.get(v.question)
        slow = bool(v.passed and cur is not None and base and cur > CANARY_SLOW_MULTIPLIER * base)
        bad = [r for r in v.replicates if not r.passed]
        c = corpus.get(v.question_id, {})
        reps = []
        for rv in v.replicates:
            rec = rec_by.get((v.question, rv.replicate_index))
            reps.append({"i": rv.replicate_index, "passed": rv.passed, "reason": rv.reason, "answer": rv.answer,
                         "branch": rec.branch.capitalize() if rec else "",
                         "seconds": f"{rec.latency_ms.get('total', 0) / 1000:.1f} s" if rec else ""})
        questions.append({
            "id": v.question_id, "question": v.question,
            "status": "fail" if not v.passed else ("slow" if slow else "pass"),
            "judge": bad[0].reason if bad else f"{len(v.replicates)} of {len(v.replicates)} pass",
            "base": f"{base / 1000:.1f} s" if base else DASH,
            "now": f"{cur / 1000:.1f} s" if cur is not None else DASH,
            "category": CANARY_CATEGORY_LABELS.get(c.get("category", ""), c.get("category", "")),
            "expected": c.get("expected_behaviour", ""), "replicates": reps,
        })
    cats: dict[str, dict] = {}
    for q in questions:
        d = cats.setdefault(q["category"], {"category": q["category"], "n": 0, "pass": 0, "fail": 0, "slow": 0})
        d["n"] += 1
        d[q["status"]] += 1
    return {"latest": latest_id, "latest_ts": _iso(min(r.timestamp for r in latest)),
            "latest_sha": _short_sha(latest[0].git_sha), "judged": bool(verdicts),
            "runs": run_rows, "questions": questions,
            "categories": sorted(cats.values(), key=lambda d: (-d["fail"], -d["slow"], d["category"]))}


def _writer_state(reader: LogReader) -> dict | None:
    """``hf_writer_state.json`` from production, or None for a local log.
    A failed fetch is reported as the writer's error so it shows red."""
    primary = _production_reader(reader)
    if primary is None:
        return None
    from hf_log_writer import read_writer_state

    try:
        state = read_writer_state(primary._api, repo_id=primary._repo_id)
    except Exception as exc:
        return {"last_flush_time": None, "buffer_size": None,
                "last_error": f"could not read the writer state: {type(exc).__name__}: {exc}"}
    if state is None:
        return {"last_flush_time": None, "buffer_size": None,
                "last_error": "no writer state file: the writer has never flushed"}
    return state


def _kb_coverage_entries(records: list[InteractionRecord]) -> list[CoverageEntry]:
    flat = [chunk for r in records for chunk in r.retrieved_chunks]
    return compute_coverage(flat, load_sections())


def _build_flags(model: DashboardModel) -> list[Flag]:
    return [
        *detect_gap_rate_jump(model.records),
        *detect_new_cluster(
            read_clusters(CLUSTERS_DEFAULT_PATH),
            read_cluster_history(CLUSTERS_ARCHIVE_DIR),
        ),
        *detect_repeat_failure(model.records),
    ]


def build_page(
    reader: LogReader,
    *,
    provided_session_ids: frozenset[str] | None = None,
    verdicts_dir: Path = DEFAULT_VERDICTS_DIR,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    clusters_path: Path = CLUSTERS_DEFAULT_PATH,
    summaries_dir: Path = DEFAULT_SUMMARIES_DIR,
    batch_messages: list[str] | None = None,
) -> dict:
    """Everything the page shows, as plain data. A failed read gives a page
    with ``failed`` set and no figures."""
    read_at = datetime.now(timezone.utc)
    production = _production_reader(reader) is not None
    source = {"production": production, "label": "Production log" if production else "Local log",
              "read_at": read_at.isoformat()}
    try:
        all_records = reader.read()
        if provided_session_ids is None:
            # Contacts from the same source as the log, so --local never
            # joins local turns with production submissions.
            provided_session_ids = frozenset(read_provided_session_ids(
                reader=make_contact_reader(force_local=not production)))
    except LogReadError as exc:
        return {"failed": str(exc), "source": source, "commands": COMMANDS}
    report = reader.report
    model = DashboardModel(all_records, provided_session_ids=provided_session_ids)
    live = model.records
    source.update({
        "records": len(live), "files_read": report.files_read,
        "unreadable_lines": report.unreadable_lines, "duplicates": report.duplicates,
        "newest": max((_iso(r.timestamp) for r in live), default=None),
    })
    sections, totals = _metrics_section(model)
    coverage = [{"section": e.section_heading, "file": e.source_file, "count": e.retrieval_count,
                 "off": e.off_canon} for e in _kb_coverage_entries(live)]
    return {
        "failed": None, "source": source, "commands": COMMANDS,
        "writer": _writer_state(reader),
        "batch_messages": [m for m in (batch_messages or []) if m],
        "flags": [{"headline": f.headline, "detail": f.detail} for f in _build_flags(model)],
        "metrics": sections, "window_labels": WINDOW_LABELS, "window_totals": totals,
        "failures": _failures_section(live),
        "canary": _canary_section(all_records, verdicts_dir=verdicts_dir,
                                  baseline_path=baseline_path, corpus_path=corpus_path),
        # Built from production only; a local page does not show them.
        "clusters": read_clusters(clusters_path) if production else None,
        "deflection": read_summary("deflection", summaries_dir) if production else None,
        "coverage": coverage,
    }


# ---- Render -------------------------------------------------------------------------


def render(page: dict) -> str:
    """The page as one HTML file. A failed read renders without any data:
    a red notice, the reason and how to retry."""
    if page.get("failed"):
        return _render_failed(page)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(page, default=str).replace("</", "<\\/")
    return template.replace("/*__DATA__*/null", payload)


def _render_failed(page: dict) -> str:
    import html as _html

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel</title>
<style>
body {{ margin:0; background:#FAF9F5; color:#141413; font:15px/1.5 system-ui, 'Segoe UI', Roboto, sans-serif; }}
.wrap {{ max-width:880px; margin:0 auto; padding:56px 24px; }}
h1 {{ font:400 34px/1.2 Georgia, serif; margin:0 0 12px; }}
.status {{ display:inline-flex; align-items:center; gap:8px; }}
.dot {{ width:8px; height:8px; border-radius:50%; background:#B5483B; }}
.reason {{ font:13px/1.6 'SF Mono', Monaco, monospace; background:#F5F4ED; border-radius:8px; padding:12px 14px; margin:16px 0; }}
.muted {{ color:#5E5D59; }}
</style></head><body><div class="wrap">
<p class="status"><span class="dot"></span>Log read failed</p>
<h1>Sentinel could not read the whole log, so it shows no numbers.</h1>
<p class="muted">{_html.escape(page["source"]["label"])}, tried at {_html.escape(page["source"]["read_at"][:16].replace("T", " "))} UTC. A partial read would undercount every figure.</p>
<div class="reason">{_html.escape(page["failed"])}</div>
<p class="muted">Fix the cause, then run <code>{_html.escape(page["commands"]["refresh"])}</code> again.</p>
</div></body></html>
"""


def main(argv: list[str] | None = None) -> Path:
    args = _parse_cli_args(argv)
    # Production or local is decided by HF_TOKEN; load it explicitly rather
    # than relying on an import elsewhere having read .env.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    reader = _wrap_with_canary_overlay_if_hf(make_log_reader(force_local=args.local))
    # The caches describe production, so only a production run rebuilds them.
    # A failed read inside a batch comes back as its message; build_page then
    # reads again and shows the failed read instead of any figure.
    messages = [
        ensure_fresh_clusters(out_path=CLUSTERS_DEFAULT_PATH, archive_dir=CLUSTERS_ARCHIVE_DIR, reader=reader),
        ensure_fresh_summaries(out_dir=DEFAULT_SUMMARIES_DIR, reader=reader),
    ] if _production_reader(reader) is not None else []
    page = build_page(reader, clusters_path=CLUSTERS_DEFAULT_PATH,
                      summaries_dir=DEFAULT_SUMMARIES_DIR, batch_messages=messages)
    PAGE_PATH.write_text(render(page), encoding="utf-8")
    print(f"Sentinel written to {PAGE_PATH}")
    if not args.no_open:
        webbrowser.open(PAGE_PATH.resolve().as_uri())
    return PAGE_PATH


def _parse_cli_args(argv: list[str] | None = None):
    """``--local`` reads the local log even when production credentials are
    set; ``--no-open`` writes the page without opening a browser."""
    import argparse

    parser = argparse.ArgumentParser(prog="sentinel", description="Digital Twin Sentinel page.")
    parser.add_argument(
        "--local", action="store_true",
        help="Read data/logs/interactions.jsonl even when HF_TOKEN and HF_DATASET_REPO are set.",
    )
    parser.add_argument("--no-open", action="store_true", help="Write the page without opening it.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()

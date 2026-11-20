"""Independent recomputation of the figures Sentinel shows (issue #61).

Rebuilds every number from the raw files: the daily JSONL files in the
Hugging Face log dataset, the local canary records and the judged verdict
files. It imports nothing from `src/`, so a bug in Sentinel's reader or
model cannot hide here. Definitions follow the metric names and
`docs/SENTINEL.md`; where a definition leaves a choice open, the choice is
stated beside the figure.

Any failure in the data path stops the script with a non-zero exit: a
listing error, a day file that will not download, a line that is not valid
JSON. It never returns a partial picture.

    uv run python scripts/sentinel_recompute.py                 # read production
    uv run python scripts/sentinel_recompute.py --snapshot DIR  # read a saved copy
    uv run python scripts/sentinel_recompute.py --save DIR      # read production, keep a copy
    uv run python scripts/sentinel_recompute.py --json out.json

Read-only: it lists and downloads, nothing else.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_LOG = REPO_ROOT / "data" / "logs" / "interactions.jsonl"
VERDICTS_DIR = REPO_ROOT / "data" / "canaries" / "verdicts"
BASELINE = REPO_ROOT / "data" / "canaries" / "baseline.json"
CORPUS = REPO_ROOT / "data" / "canaries" / "corpus.json"
KB_DIR = REPO_ROOT / "data" / "knowledge_base"
GAP_CLUSTERS = REPO_ROOT / "data" / "logs" / "gap_clusters.json"
GAP_ARCHIVE = REPO_ROOT / "data" / "logs" / "gap_clusters_archive"

WINDOWS = {"7d": 7, "30d": 30, "90d": 90, "global": None}
BRANCHES = ["GENERIC", "GAP", "TECHNICAL", "BEHAVIOURAL", "LOGISTICAL"]
EVENTS = ["answered", "gap", "deflected", "refused"]
STAGES = ["classifier", "retrieval", "generation", "guardrail", "total"]
MAX_ATTEMPTS = 3
REQUIRED = ["timestamp", "session_id", "turn_index", "question", "event_type",
            "branch", "classification_confidence", "attempts", "retrieved_chunks",
            "latency_ms", "knew_answer"]


class DataPathError(RuntimeError):
    """The raw data could not be read completely. Never caught, never softened."""


# --------------------------------------------------------------------- loading

def fetch_production(dest: Path) -> None:
    """Download every file of the log dataset into `dest`. Any error raises."""
    from dotenv import load_dotenv
    from huggingface_hub import HfApi, hf_hub_download

    load_dotenv(REPO_ROOT / ".env")
    repo = os.environ.get("HF_DATASET_REPO")
    token = os.environ.get("HF_TOKEN")
    if not repo or not token:
        raise DataPathError("HF_DATASET_REPO and HF_TOKEN must both be set to read production")
    files = HfApi(token=token).list_repo_files(repo, repo_type="dataset")
    wanted = [f for f in files if f.startswith(("logs/", "contacts/")) or f == "hf_writer_state.json"]
    if not any(f.startswith("logs/") for f in wanted):
        raise DataPathError(f"dataset {repo} lists no logs/ files")
    for name in wanted:
        hf_hub_download(repo, name, repo_type="dataset", token=token, local_dir=dest)


def read_jsonl_strict(path: Path) -> list[dict]:
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise DataPathError(f"{path.name}:{lineno} is not valid JSON ({e})") from e
    return rows


def load_production(snapshot: Path) -> tuple[list[dict], list[dict], dict | None, dict]:
    """Return (records, contacts, writer_state, integrity)."""
    day_files = sorted((snapshot / "logs").glob("*.jsonl"))
    if not day_files:
        raise DataPathError(f"no day files under {snapshot / 'logs'}")
    records, per_file = [], {}
    for f in day_files:
        rows = read_jsonl_strict(f)
        per_file[f.stem] = len(rows)
        for i, r in enumerate(rows):
            missing = [k for k in REQUIRED if k not in r]
            if missing:
                raise DataPathError(f"{f.name} record {i + 1} lacks {missing}")
            r["_day_file"] = f.stem
        records.extend(rows)
    contacts = [r for f in sorted((snapshot / "contacts").glob("*.jsonl")) for r in read_jsonl_strict(f)]
    state_path = snapshot / "hf_writer_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else None

    def key(r):
        return (r["session_id"], r["turn_index"], r["timestamp"])

    dup_keys = [k for k, n in Counter(key(r) for r in records).items() if n > 1]
    session_turn_repeats = [k for k, n in Counter((r["session_id"], r["turn_index"]) for r in records).items() if n > 1]
    integrity = {
        "day_files": len(day_files),
        "records": len(records),
        "records_per_file": per_file,
        "first_day": day_files[0].stem,
        "last_day": day_files[-1].stem,
        "exact_duplicates (same session, turn and timestamp)": len(dup_keys),
        "session+turn pairs used more than once": len(session_turn_repeats),
        "records filed under a day that is not their UTC day": sum(
            1 for r in records if r["timestamp"][:10] != r["_day_file"]),
        "records flagged is_canary in production": sum(1 for r in records if r.get("is_canary")),
        "schema_versions": dict(Counter(r.get("schema_version") for r in records)),
        "event_types outside the four known": sum(1 for r in records if r["event_type"] not in EVENTS),
        "branches outside the five known": sum(1 for r in records if r["branch"] not in BRANCHES),
        "records with no retrieved chunks": sum(1 for r in records if not r["retrieved_chunks"]),
        "records with no git_sha": sum(1 for r in records if not r.get("git_sha")),
        "contacts": len(contacts),
    }
    return records, contacts, state, integrity


# --------------------------------------------------------------------- helpers

def ts(r: dict) -> datetime:
    return datetime.fromisoformat(r["timestamp"])


def pct(q: float, xs: list[float]) -> float | None:
    """Percentile by linear interpolation between closest ranks (numpy default)."""
    if not xs:
        return None
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def pct_nearest(q: float, xs: list[float]) -> float | None:
    """Percentile by nearest rank, shown beside the interpolated one."""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def rate(num: int, den: int) -> dict:
    return {"value": (num / den) if den else None, "num": num, "n": den}


def in_window(records: list[dict], now: datetime, days: int | None) -> list[dict]:
    if days is None:
        return list(records)
    start = now - timedelta(days=days)
    return [r for r in records if ts(r) >= start]


# --------------------------------------------------------------------- metrics

def metrics(records: list[dict], contact_sessions: set[str]) -> dict:
    """Every Metrics-tab figure for one set of records (one window, or one branch)."""
    n = len(records)
    out: dict = {"total_interactions": n}
    ev = Counter(r["event_type"] for r in records)
    out["answered_with_substance_rate"] = rate(ev["answered"], n)
    out["gap_rate"] = rate(ev["gap"], n)
    out["deflection_rate"] = rate(ev["deflected"], n)
    out["refusal_rate"] = rate(ev["refused"], n)
    out["guardrail_rejection_rate"] = rate(
        sum(1 for r in records if any(a.get("is_acceptable") is False for a in r["attempts"])), n)
    out["retry_exhausted_rate"] = rate(sum(1 for r in records if len(r["attempts"]) >= MAX_ATTEMPTS), n)
    att = Counter(min(len(r["attempts"]), MAX_ATTEMPTS) for r in records)
    out["attempts_distribution"] = {str(k): rate(att[k], n) for k in (1, 2, 3)}
    out["records_with_zero_attempts"] = att[0]

    br = Counter(r["branch"] for r in records)
    out["branch_distribution"] = {b: rate(br[b], n) for b in BRANCHES}
    conf = [r["classification_confidence"] for r in records]
    out["mean_classification_confidence"] = {"value": statistics.fmean(conf) if conf else None, "n": n}
    out["mean_confidence_by_branch"] = {
        b: {"value": statistics.fmean(c) if (c := [r["classification_confidence"] for r in records if r["branch"] == b]) else None,
            "n": br[b]}
        for b in BRANCHES}
    out["low_confidence_rate"] = rate(sum(1 for c in conf if c < 0.7), n)

    per_session = Counter(r["session_id"] for r in records)
    out["unique_sessions"] = len(per_session)
    out["mean_turns_per_session"] = {"value": n / len(per_session) if per_session else None, "n": len(per_session)}
    out["turns_per_session_median"] = {
        "value": statistics.median(per_session.values()) if per_session else None, "n": len(per_session)}

    out["contact_offer_rate"] = rate(sum(1 for r in records if r.get("contact_offered")), n)
    offered = {r["session_id"] for r in records if r.get("contact_offered")}
    provided_in_log = {r["session_id"] for r in records if r.get("contact_provided")}
    converted = offered & (provided_in_log | contact_sessions)
    out["contact_conversion_rate (sessions offered the form that submitted it)"] = rate(len(converted), len(offered))
    all_sessions = set(per_session)
    out["sessions_that_submitted_contact (any, offered or not)"] = len(all_sessions & (provided_in_log | contact_sessions))

    calls = [c for r in records for c in r.get("tool_calls") or []]
    out["tool_call_count"] = len(calls)
    tech = [r for r in records if r["branch"] == "TECHNICAL"]
    out["technical_tool_call_rate"] = rate(sum(1 for r in tech if r.get("tool_calls")), len(tech))
    out["tool_call_success_rate"] = rate(sum(1 for c in calls if c.get("status") == "success"), len(calls))

    lat = {}
    total_p95 = pct(0.95, [r["latency_ms"]["total"] for r in records if "total" in r["latency_ms"]])
    for s in STAGES:
        xs = [r["latency_ms"][s] for r in records if s in r["latency_ms"]]
        p95 = pct(0.95, xs)
        lat[s] = {"p50_ms": pct(0.5, xs), "p95_ms": p95,
                  "p50_ms_nearest_rank": pct_nearest(0.5, xs), "p95_ms_nearest_rank": pct_nearest(0.95, xs),
                  "share_of_total_p95": (p95 / total_p95) if (p95 is not None and total_p95) else None,
                  "n": len(xs)}
    out["latency"] = lat
    return out


def failure_feed(records: list[dict]) -> dict:
    """Row counts for the Failures tab, one count per kind (kinds are disjoint here)."""
    kinds = Counter()
    for r in records:
        rejected = any(a.get("is_acceptable") is False for a in r["attempts"])
        if r["event_type"] == "refused":
            kinds["refused"] += 1
        elif len(r["attempts"]) >= MAX_ATTEMPTS:
            kinds["retry_exhausted_then_accepted"] += 1
        elif rejected:
            kinds["rejected_then_recovered"] += 1
        elif r["event_type"] == "gap":
            kinds["gap"] += 1
        elif r["event_type"] == "deflected":
            kinds["deflected"] += 1
    return {"disjoint_kinds": dict(kinds),
            "event_gap_total": sum(1 for r in records if r["event_type"] == "gap"),
            "event_deflected_total": sum(1 for r in records if r["event_type"] == "deflected"),
            "any_attempt_rejected_total": sum(
                1 for r in records if any(a.get("is_acceptable") is False for a in r["attempts"]))}


def flags(live: list[dict], now: datetime) -> dict:
    cur = [r for r in live if now - timedelta(days=7) <= ts(r)]
    prior = [r for r in live if now - timedelta(days=14) <= ts(r) < now - timedelta(days=7)]
    g = lambda rs: (sum(1 for r in rs if r["event_type"] == "gap") / len(rs)) if rs else None  # noqa: E731
    jump = (g(cur) - g(prior)) if (cur and prior) else None
    norm = lambda q: re.sub(r"\s+", " ", q.strip().lower())  # noqa: E731
    rep = Counter(norm(r["question"]) for r in cur if r["event_type"] in ("deflected", "refused"))
    out = {
        "gap_rate_jump": {"current_7d": g(cur), "n_current": len(cur), "prior_7d": g(prior), "n_prior": len(prior),
                          "delta": jump, "fires (delta > 0.30)": bool(jump is not None and jump > 0.30)},
        "repeat_failure": {q: c for q, c in rep.items() if c >= 3},
    }
    if GAP_CLUSTERS.exists():
        latest = json.loads(GAP_CLUSTERS.read_text())
        seen = set()
        for f in GAP_ARCHIVE.glob("gap_clusters_*.json") if GAP_ARCHIVE.exists() else []:
            seen |= {c.get("label") for c in json.loads(f.read_text()).get("clusters", [])}
        labels = [c.get("label") for c in latest.get("clusters", [])]
        out["new_cluster"] = {"latest_generated_at": latest.get("generated_at"), "latest_clusters": len(labels),
                              "labels_in_no_archive_file": [x for x in labels if x not in seen]}
    else:
        out["new_cluster"] = {"latest_generated_at": None}
    return out


def canonical_sections() -> set[tuple[str, str]]:
    """(file, section heading) for every chunk the knowledge base produces."""
    canon = set()
    for f in sorted(KB_DIR.glob("*.md")):
        if f.name in ("SUMMARY.md", "INDEX.md"):
            canon.add((f.name, f.stem))
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
        # The text before the first "## " is a chunk of its own, named after the
        # file, when it holds more than the H1 title and rules (ingest.py's rule).
        preamble = lines[: heads[0]] if heads else lines
        if any(x.strip() and not x.startswith("# ") and x.strip() != "---" for x in preamble):
            canon.add((f.name, f.stem))
        canon |= {(f.name, lines[i][3:].strip()) for i in heads}
    return canon


def kb_coverage(records: list[dict]) -> dict:
    canon = canonical_sections()
    hits = Counter((c.get("source_file"), c.get("section_heading")) for r in records for c in r["retrieved_chunks"])
    never = sorted(canon - set(hits))
    off = sorted(k for k in hits if k not in canon)
    return {"canonical_sections": len(canon), "retrieved_sections": len(canon & set(hits)),
            "never_retrieved": len(never), "off_canon": len(off),
            "never_retrieved_list": [" :: ".join(k) for k in never],
            "off_canon_list": [f"{k[0]} :: {k[1]} ({hits[k]})" for k in off],
            "retrieval_events": sum(hits.values()),
            "least_retrieved": [f"{k[0]} :: {k[1]} ({n})" for k, n in sorted(hits.items(), key=lambda kv: kv[1])[:10] if k in canon]}


def canary() -> dict:
    if not LOCAL_LOG.exists():
        return {"error": f"{LOCAL_LOG} missing"}
    local = read_jsonl_strict(LOCAL_LOG)
    runs: dict[str, list[dict]] = defaultdict(list)
    for r in local:
        if r.get("is_canary"):
            runs[r["run_id"]].append(r)
    order = sorted(runs, key=lambda k: min(x["timestamp"] for x in runs[k]))
    latest = order[-1]
    corpus = json.loads(CORPUS.read_text())
    baseline = json.loads(BASELINE.read_text())
    qid = lambda r: r["session_id"].rsplit("-", 1)[-1]  # noqa: E731
    out = {"local_file_records": len(local), "local_canary_records": sum(len(v) for v in runs.values()),
           "local_live_records": sum(1 for r in local if not r.get("is_canary")),
           "runs": [{"run_id": k, "records": len(runs[k]), "started": min(x["timestamp"] for x in runs[k]),
                     "git_sha": (runs[k][0].get("git_sha") or "")[:7],
                     "judged": (VERDICTS_DIR / f"{k}.jsonl").exists()} for k in order],
           "latest_run": latest, "corpus_questions": len(corpus), "baseline_run": baseline.get("run_id")}
    vfile = VERDICTS_DIR / f"{latest}.jsonl"
    if vfile.exists():
        verdicts = read_jsonl_strict(vfile)
        by_q: dict[str, list[bool]] = defaultdict(list)
        for v in verdicts:
            by_q[v["question_id"]].append(bool(v["passed"]))
        failing = sorted(q for q, ps in by_q.items() if not all(ps))
        out["latest_run_verdict"] = {
            "replicates_judged": len(verdicts), "replicates_passed": sum(1 for v in verdicts if v["passed"]),
            "questions_judged": len(by_q), "questions_passing": len(by_q) - len(failing),
            "questions_failing": failing,
            "questions_in_corpus_without_a_verdict": sorted({q["id"] for q in corpus} - set(by_q)),
            "replicates_per_question": dict(Counter(len(ps) for ps in by_q.values()))}
    else:
        out["latest_run_verdict"] = None

    def med_by_q(run_id):
        d = defaultdict(list)
        for r in runs.get(run_id, []):
            d[qid(r)].append(r["latency_ms"]["total"])
        return {q: statistics.median(v) for q, v in d.items()}

    base, cur = med_by_q(baseline.get("run_id")), med_by_q(latest)
    out["slow_questions (median total latency over 1.5x the baseline median)"] = sorted(
        q for q in cur if q in base and cur[q] > 1.5 * base[q])
    out["stage_p95_ms"] = {
        k: {s: pct(0.95, [r["latency_ms"][s] for r in runs[k]]) for s in STAGES}
        for k in order if k == baseline.get("run_id") or order.index(k) > order.index(baseline.get("run_id"))
    } if baseline.get("run_id") in order else {}
    return out


# ------------------------------------------------------------------------ main

def recompute(snapshot: Path, now: datetime) -> dict:
    records, contacts, state, integrity = load_production(snapshot)
    live = [r for r in records if not r.get("is_canary")]
    contact_sessions = {c["session_id"] for c in contacts}
    newest = max(ts(r) for r in live)
    result = {
        "computed_at_utc": now.isoformat(),
        "window_rule": "a record is in an N-day window when its timestamp >= now - N days; 'now' is the time above",
        "percentile_rule": "linear interpolation between closest ranks; nearest-rank shown beside it",
        "integrity": integrity,
        "newest_record_utc": newest.isoformat(),
        "newest_record_age_days": (now - newest).total_seconds() / 86400,
        "writer_state": state,
        "writer_last_flush_age_hours": (
            (now - datetime.fromisoformat(state["last_flush_time"])).total_seconds() / 3600
            if state and state.get("last_flush_time") else None),
        "days_with_records_in_last_30": len({r["_day_file"] for r in in_window(live, now, 30)}),
        "longest_gap_between_record_days": _longest_gap(sorted({r["_day_file"] for r in live})),
        "windows": {}, "by_branch": {}, "failure_feed": {},
    }
    for w, days in WINDOWS.items():
        rs = in_window(live, now, days)
        result["windows"][w] = metrics(rs, contact_sessions)
        result["by_branch"][w] = {b: metrics([r for r in rs if r["branch"] == b], contact_sessions) for b in BRANCHES}
        result["failure_feed"][w] = failure_feed(rs)
    result["flags"] = flags(live, now)
    result["kb_coverage"] = {"production_live_records_only": kb_coverage(live)}
    result["canary"] = canary()
    return result


def _longest_gap(days: list[str]) -> dict:
    best = {"days": 0, "from": None, "to": None}
    for a, b in zip(days, days[1:]):
        d = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
        if d > best["days"]:
            best = {"days": d, "from": a, "to": b}
    return best


def _fmt(v) -> str:
    if isinstance(v, dict) and "value" in v:
        val, n = v["value"], v.get("n")
        if val is None:
            return f"none (n={n})"
        if "num" in v:
            return f"{val * 100:.1f}% ({n})"
        return f"{val:.3f} ({n})"
    return str(v)


def print_table(res: dict) -> None:
    print(f"computed {res['computed_at_utc']}")
    print("\nINTEGRITY")
    for k, v in res["integrity"].items():
        if k != "records_per_file":
            print(f"  {k}: {v}")
    print(f"  newest record: {res['newest_record_utc']} ({res['newest_record_age_days']:.2f} days old)")
    print(f"  writer state: {res['writer_state']} (last flush {res['writer_last_flush_age_hours']:.1f} h ago)"
          if res["writer_last_flush_age_hours"] is not None else f"  writer state: {res['writer_state']}")
    print(f"  longest gap between days with records: {res['longest_gap_between_record_days']}")
    scalar = [k for k, v in res["windows"]["global"].items()
              if not isinstance(v, dict) or "value" in v]
    print("\nMETRICS (live records)            " + "".join(f"{w:>18}" for w in WINDOWS))
    for k in scalar:
        print(f"  {k[:32]:<32}" + "".join(f"{_fmt(res['windows'][w][k]):>18}" for w in WINDOWS))
    for group in ("attempts_distribution", "branch_distribution", "mean_confidence_by_branch"):
        for sub in res["windows"]["global"][group]:
            print(f"  {(group[:20] + ' ' + sub)[:32]:<32}"
                  + "".join(f"{_fmt(res['windows'][w][group][sub]):>18}" for w in WINDOWS))
    for s in STAGES:
        row = ""
        for w in WINDOWS:
            m = res["windows"][w]["latency"][s]
            row += f"{'-' if m['p50_ms'] is None else f'''{m['p50_ms'] / 1000:.1f}|{m['p95_ms'] / 1000:.1f}s ({m['n']})''':>18}"
        print(f"  {'latency p50|p95 ' + s:<32}{row}")
    print("\nFAILURE FEED (global):", res["failure_feed"]["global"])
    print("FLAGS:", json.dumps(res["flags"], indent=1))
    kb = res["kb_coverage"]["production_live_records_only"]
    print(f"\nKB COVERAGE: {kb['canonical_sections']} sections, {kb['retrieved_sections']} retrieved, "
          f"{kb['never_retrieved']} never, {kb['off_canon']} off-canon")
    c = res["canary"]
    print(f"\nCANARY: latest {c.get('latest_run')}, verdict {c.get('latest_run_verdict')}")
    print(f"  slow: {c.get('slow_questions (median total latency over 1.5x the baseline median)')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot", type=Path, help="read a saved copy of the dataset instead of production")
    ap.add_argument("--save", type=Path, help="when reading production, keep the downloaded copy here")
    ap.add_argument("--now", help="ISO time to anchor the windows (default: the current UTC time)")
    ap.add_argument("--json", type=Path, help="also write the full result as JSON")
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if args.snapshot:
        res = recompute(args.snapshot, now)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            dest = args.save or Path(tmp)
            dest.mkdir(parents=True, exist_ok=True)
            fetch_production(dest)
            res = recompute(dest, now)
    print_table(res)
    if args.json:
        args.json.write_text(json.dumps(res, indent=1, default=str))
        print(f"\nfull result: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

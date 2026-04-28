"""
Plot eval results across runs.

Usage:
    uv run projects/digital-twin/eval/plot_eval.py
    uv run projects/digital-twin/eval/plot_eval.py --runs v1 v2 v3
    uv run projects/digital-twin/eval/plot_eval.py --output eval/results/comparison.png
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

RESULTS_DIR = Path(__file__).parent / "results"
CATEGORIES = ["comparative", "direct_fact", "holistic", "numerical", "relationship", "spanning", "temporal"]
RETRIEVAL_METRICS = ["mrr", "ndcg", "keyword_coverage"]
ANSWER_METRICS = ["accuracy", "completeness", "relevance"]
RETRIEVAL_LABELS = {"mrr": "MRR", "ndcg": "nDCG", "keyword_coverage": "Coverage (%)"}
ANSWER_LABELS = {"accuracy": "Accuracy", "completeness": "Completeness", "relevance": "Relevance"}
RETRIEVAL_MAX = {"mrr": 1.0, "ndcg": 1.0, "keyword_coverage": 100.0}
ANSWER_MAX = 5.0


def load_run(path: Path) -> dict:
    return json.loads(path.read_text())


def pick_runs(requested: list[str] | None) -> list[Path]:
    all_paths = sorted(RESULTS_DIR.glob("v*.json"), key=lambda p: int(p.stem.split("_")[0][1:]))
    if not requested:
        return all_paths
    matched = []
    for r in requested:
        candidates = [p for p in all_paths if p.stem.startswith(r)]
        if not candidates:
            raise FileNotFoundError(f"No result file matching '{r}'")
        matched.append(candidates[0])
    return matched


def _bar_group(ax, categories, run_labels, values_by_run, metric_max, target=None, ylabel="", title=""):
    n_cats = len(categories)
    n_runs = len(run_labels)
    width = 0.7 / n_runs
    x = np.arange(n_cats)
    colors = plt.cm.tab10(np.linspace(0, 0.6, n_runs))

    for i, (label, vals, color) in enumerate(zip(run_labels, values_by_run, colors)):
        offset = (i - (n_runs - 1) / 2) * width
        bars = ax.bar(x + offset, vals, width, label=label, color=color, alpha=0.85)

    if target is not None:
        ax.axhline(target, color="crimson", linestyle="--", linewidth=1, label=f"Target ({target})")

    ax.set_xticks(x)
    ax.set_xticklabels([c.replace("_", "\n") for c in categories], fontsize=8)
    ax.set_ylim(0, metric_max * 1.08)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)


def plot(run_paths: list[Path], output: Path | None) -> None:
    runs = [load_run(p) for p in run_paths]
    labels = [r["run_id"] for r in runs]

    fig, axes = plt.subplots(3, 3, figsize=(16, 12))
    fig.suptitle("Digital Twin RAG — Eval Comparison by Category", fontsize=13, fontweight="bold", y=1.01)

    # --- Retrieval metrics (row 0) ---
    for col, metric in enumerate(RETRIEVAL_METRICS):
        vals_by_run = [
            [r["by_category"]["retrieval"].get(cat, {}).get(metric, 0) for cat in CATEGORIES]
            for r in runs
        ]
        target = 0.75 if metric in ("mrr", "ndcg") else None
        _bar_group(
            axes[0, col], CATEGORIES, labels, vals_by_run,
            RETRIEVAL_MAX[metric], target=target,
            ylabel=RETRIEVAL_LABELS[metric], title=f"Retrieval — {RETRIEVAL_LABELS[metric]}",
        )

    # --- Answer metrics (row 1) ---
    for col, metric in enumerate(ANSWER_METRICS):
        vals_by_run = [
            [r["by_category"]["answer"].get(cat, {}).get(metric, 0) for cat in CATEGORIES]
            for r in runs
        ]
        target = 4.0 if metric in ("accuracy", "relevance") else None
        _bar_group(
            axes[1, col], CATEGORIES, labels, vals_by_run,
            ANSWER_MAX, target=target,
            ylabel=f"{ANSWER_LABELS[metric]} / 5", title=f"Answer — {ANSWER_LABELS[metric]}",
        )

    # --- Summary panel (row 2): overall scores + gap rate as line plot ---
    ax_overall = axes[2, 0]
    overall_metrics = ["mrr", "ndcg"]
    for metric in overall_metrics:
        vals = [r["summary"]["retrieval"][metric] for r in runs]
        ax_overall.plot(labels, vals, marker="o", label=metric.upper())
    ax_overall.axhline(0.75, color="crimson", linestyle="--", linewidth=1, label="Target 0.75")
    ax_overall.set_ylim(0.5, 1.05)
    ax_overall.set_title("Overall Retrieval", fontsize=10, fontweight="bold")
    ax_overall.legend(fontsize=8)
    ax_overall.grid(alpha=0.3)
    ax_overall.spines[["top", "right"]].set_visible(False)

    ax_answer = axes[2, 1]
    for metric in ANSWER_METRICS:
        vals = [r["summary"]["answer"][metric] for r in runs]
        ax_answer.plot(labels, vals, marker="o", label=ANSWER_LABELS[metric])
    ax_answer.axhline(4.0, color="crimson", linestyle="--", linewidth=1, label="Target 4.0")
    ax_answer.set_ylim(0, 5.5)
    ax_answer.set_title("Overall Answer Quality", fontsize=10, fontweight="bold")
    ax_answer.legend(fontsize=8)
    ax_answer.grid(alpha=0.3)
    ax_answer.spines[["top", "right"]].set_visible(False)

    ax_gap = axes[2, 2]
    gap_vals = [r["summary"].get("gap_rate", 0) * 100 for r in runs]
    ax_gap.bar(labels, gap_vals, color=plt.cm.tab10(np.linspace(0, 0.6, len(labels))), alpha=0.85)
    ax_gap.set_title("Gap Rate (%)", fontsize=10, fontweight="bold")
    ax_gap.set_ylabel("% questions unanswered")
    ax_gap.set_ylim(0, max(gap_vals) * 1.3 + 1)
    ax_gap.grid(axis="y", alpha=0.3)
    ax_gap.spines[["top", "right"]].set_visible(False)

    # --- Architecture notes as subtitle ---
    notes = [f"{r['run_id']}: {r['architecture'].get('notes', '') or '—'}" for r in runs]
    fig.text(0.5, -0.01, "\n".join(notes), ha="center", fontsize=7.5, color="#555",
             bbox=dict(facecolor="#f9f9f9", edgecolor="#ccc", boxstyle="round,pad=0.4"))

    plt.tight_layout()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output, dpi=150, bbox_inches="tight")
        print(f"Saved → {output}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="*", help="Run IDs to include (e.g. v1 v2 v3); default: all")
    parser.add_argument("--output", type=Path, default=None, help="Save to file instead of showing")
    args = parser.parse_args()

    paths = pick_runs(args.runs)
    print(f"Comparing {len(paths)} run(s): {[p.stem for p in paths]}")
    plot(paths, args.output)


if __name__ == "__main__":
    main()

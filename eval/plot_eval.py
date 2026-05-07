"""
Plot eval results across runs.

3×3 layout:
  - Row 0: per-category retrieval (MRR / nDCG / Coverage)
  - Row 1: per-category answer quality (Accuracy / Completeness / Relevance)
  - Row 2: overall trajectory (retrieval line / answer line / gap rate bars)

Per-category panels surface "which question types regressed" — the load-bearing
question this plot answers. Architecture notes for each run live in the JSON
result files; this plot is metric-only.

Usage:
    uv run eval/plot_eval.py
    uv run eval/plot_eval.py --runs v1 v2 v3
    uv run eval/plot_eval.py --output eval/results/comparison.png
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


def _bar_group(ax, categories, n_runs, values_by_run, colors, metric_max, target=None, ylabel="", title=""):
    n_cats = len(categories)
    width = 0.78 / n_runs
    x = np.arange(n_cats)

    for i, (vals, color) in enumerate(zip(values_by_run, colors)):
        offset = (i - (n_runs - 1) / 2) * width
        ax.bar(x + offset, vals, width, color=color, alpha=0.88)

    if target is not None:
        ax.axhline(target, color="crimson", linestyle="--", linewidth=1, alpha=0.7)
        ax.text(n_cats - 0.5, target + metric_max * 0.01, f"target {target}",
                fontsize=9, color="crimson", ha="right", va="bottom")

    ax.set_xticks(x)
    ax.set_xticklabels([c.replace("_", "\n") for c in categories], fontsize=10)
    ax.set_ylim(0, metric_max * 1.08)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.tick_params(axis="y", labelsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)


def plot(run_paths: list[Path], output: Path | None) -> None:
    runs = [load_run(p) for p in run_paths]
    labels = [r["run_id"].split("_")[0] for r in runs]  # "v6" not "v6_2026-05-07"
    n_runs = len(runs)
    colors = plt.cm.tab10(np.linspace(0, 0.6, n_runs))

    fig, axes = plt.subplots(3, 3, figsize=(18, 14))
    fig.suptitle(
        f"Digital Twin RAG — eval comparison  ({labels[0]} → {labels[-1]})",
        fontsize=16, fontweight="bold", y=0.995,
    )

    # --- Per-category retrieval (row 0) ---
    for col, metric in enumerate(RETRIEVAL_METRICS):
        vals_by_run = [
            [r["by_category"]["retrieval"].get(cat, {}).get(metric, 0) for cat in CATEGORIES]
            for r in runs
        ]
        target = 0.75 if metric in ("mrr", "ndcg") else None
        _bar_group(
            axes[0, col], CATEGORIES, n_runs, vals_by_run, colors,
            RETRIEVAL_MAX[metric], target=target,
            ylabel=RETRIEVAL_LABELS[metric], title=f"Retrieval — {RETRIEVAL_LABELS[metric]}",
        )

    # --- Per-category answer quality (row 1) ---
    for col, metric in enumerate(ANSWER_METRICS):
        vals_by_run = [
            [r["by_category"]["answer"].get(cat, {}).get(metric, 0) for cat in CATEGORIES]
            for r in runs
        ]
        target = 4.0 if metric in ("accuracy", "relevance") else None
        _bar_group(
            axes[1, col], CATEGORIES, n_runs, vals_by_run, colors,
            ANSWER_MAX, target=target,
            ylabel=f"{ANSWER_LABELS[metric]} / 5", title=f"Answer — {ANSWER_LABELS[metric]}",
        )

    # --- Overall trajectory (row 2) ---
    ax_overall = axes[2, 0]
    for key, label in [("mrr", "MRR"), ("ndcg", "nDCG")]:
        vals = [r["summary"]["retrieval"][key] for r in runs]
        ax_overall.plot(labels, vals, marker="o", linewidth=2, markersize=7, label=label)
    ax_overall.axhline(0.75, color="crimson", linestyle="--", linewidth=1, alpha=0.7)
    ax_overall.text(len(labels) - 0.5, 0.755, "target 0.75",
                    fontsize=9, color="crimson", ha="right", va="bottom")
    ax_overall.set_ylim(0.5, 1.0)
    ax_overall.set_title("Overall retrieval (trajectory)", fontsize=12, fontweight="bold")
    ax_overall.legend(fontsize=10, loc="lower right", frameon=False)
    ax_overall.grid(alpha=0.3)
    ax_overall.spines[["top", "right"]].set_visible(False)
    ax_overall.tick_params(labelsize=10)

    ax_answer = axes[2, 1]
    for metric in ANSWER_METRICS:
        vals = [r["summary"]["answer"][metric] for r in runs]
        ax_answer.plot(labels, vals, marker="o", linewidth=2, markersize=7, label=ANSWER_LABELS[metric])
    ax_answer.axhline(4.0, color="crimson", linestyle="--", linewidth=1, alpha=0.7)
    ax_answer.text(len(labels) - 0.5, 4.03, "target 4.0",
                   fontsize=9, color="crimson", ha="right", va="bottom")
    ax_answer.set_ylim(3.0, 5.1)
    ax_answer.set_title("Overall answer quality (trajectory)", fontsize=12, fontweight="bold")
    ax_answer.legend(fontsize=10, loc="lower right", frameon=False)
    ax_answer.grid(alpha=0.3)
    ax_answer.spines[["top", "right"]].set_visible(False)
    ax_answer.tick_params(labelsize=10)

    ax_gap = axes[2, 2]
    gap_vals = [r["summary"].get("gap_rate", 0) * 100 for r in runs]
    bars = ax_gap.bar(labels, gap_vals, color=colors, alpha=0.88)
    for bar, v in zip(bars, gap_vals):
        ax_gap.text(bar.get_x() + bar.get_width() / 2, v + max(gap_vals + [1]) * 0.03,
                    f"{v:.1f}%", ha="center", fontsize=10)
    ax_gap.set_ylim(0, max(gap_vals + [1]) * 1.4 + 1)
    ax_gap.set_title("Gap rate (trajectory)", fontsize=12, fontweight="bold")
    ax_gap.set_ylabel("% questions unanswered", fontsize=11)
    ax_gap.grid(axis="y", alpha=0.3)
    ax_gap.spines[["top", "right"]].set_visible(False)
    ax_gap.tick_params(labelsize=10)

    # --- Single shared version legend at the top of the figure ---
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=0.88) for c in colors]
    fig.legend(
        handles, labels,
        loc="upper center", bbox_to_anchor=(0.5, 0.965),
        ncol=n_runs, fontsize=11, frameon=False,
        title="Eval runs", title_fontsize=11,
    )

    plt.tight_layout(rect=(0, 0, 1, 0.94))

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

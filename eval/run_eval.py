"""
Evaluation pipeline for the digital twin RAG system.

Computes:
  Retrieval — MRR, nDCG, keyword coverage (per question and per category)
  Answer    — accuracy, completeness, relevance via LLM-as-judge (1-5 scale)

Results are written to eval/results/v{N}_{date}.json with a full architecture
snapshot so runs can be compared over time.

Usage:
    uv run eval/run_eval.py
    uv run eval/run_eval.py --notes "after reranker prompt change"
    uv run eval/run_eval.py --retrieval-only
    uv run eval/run_eval.py --answer-only
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from chromadb import PersistentClient
from dotenv import load_dotenv
from litellm import completion
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from answer import FINAL_K, GAP_PHRASE, MODEL, RETRIEVAL_K, answer_question, fetch_context

load_dotenv(override=True)

TESTS_PATH = Path(__file__).parent / "tests.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"
DB_PATH = str(Path(__file__).parent.parent / "data" / "preprocessed_db")
KB_DIR = Path(__file__).parent.parent / "data" / "knowledge_base"

# Separate model for judging — should be stronger than the model under evaluation
JUDGE_MODEL = "openai/gpt-4.1"

wait = wait_exponential(multiplier=1, min=10, max=120)
stop = stop_after_attempt(5)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class EvalQuestion(BaseModel):
    question: str
    keywords: list[str]
    reference_answer: str
    category: str


class RetrievalResult(BaseModel):
    mrr: float
    ndcg: float
    keywords_found: int
    total_keywords: int
    keyword_coverage: float  # 0–100


class AnswerResult(BaseModel):
    accuracy: float = Field(description="1 (wrong) to 5 (perfect). Any factual error must score 1.")
    completeness: float = Field(description="1 (missing key info) to 5 (all reference info present).")
    relevance: float = Field(description="1 (off-topic) to 5 (answers exactly what was asked, no padding).")
    feedback: str = Field(description="Concise explanation of the scores.")


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------


def _reciprocal_rank(keyword: str, docs: list) -> float:
    kw = keyword.lower()
    for rank, doc in enumerate(docs, start=1):
        if kw in doc.page_content.lower():
            return 1.0 / rank
    return 0.0


def _dcg(relevances: list[int], k: int) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def _ndcg(keyword: str, docs: list, k: int = 10) -> float:
    kw = keyword.lower()
    rels = [1 if kw in doc.page_content.lower() else 0 for doc in docs[:k]]
    ideal = _dcg(sorted(rels, reverse=True), k)
    return _dcg(rels, k) / ideal if ideal > 0 else 0.0


def eval_retrieval(test: EvalQuestion) -> RetrievalResult:
    docs = fetch_context(test.question)
    rr = [_reciprocal_rank(kw, docs) for kw in test.keywords]
    ng = [_ndcg(kw, docs) for kw in test.keywords]
    found = sum(1 for s in rr if s > 0)
    n = len(test.keywords)
    return RetrievalResult(
        mrr=sum(rr) / n if n else 0.0,
        ndcg=sum(ng) / n if n else 0.0,
        keywords_found=found,
        total_keywords=n,
        keyword_coverage=found / n * 100 if n else 0.0,
    )


# ---------------------------------------------------------------------------
# Answer quality (LLM-as-judge)
# ---------------------------------------------------------------------------


@retry(wait=wait, stop=stop)
def eval_answer(test: EvalQuestion) -> tuple[AnswerResult, str]:
    generated, _ = answer_question(test.question)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert evaluator of answer quality. "
                "Score strictly — only award 5 for a perfect answer. "
                "If any factual claim is wrong or invented, accuracy must be 1."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {test.question}\n\n"
                f"Generated answer:\n{generated}\n\n"
                f"Reference answer:\n{test.reference_answer}\n\n"
                "Score the generated answer on three dimensions (1–5):\n"
                "- accuracy: factual correctness versus the reference answer\n"
                "- completeness: covers all information present in the reference answer\n"
                "- relevance: directly answers the question with no padding or off-topic content\n\n"
                "Provide brief feedback explaining the scores."
            ),
        },
    ]
    response = completion(model=JUDGE_MODEL, messages=messages, response_format=AnswerResult)
    result = AnswerResult.model_validate_json(response.choices[0].message.content)
    return result, generated


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _agg_retrieval(records: list[dict]) -> dict:
    return {k: _mean([r[k] for r in records]) for k in ("mrr", "ndcg", "keyword_coverage")}


def _agg_answer(records: list[dict]) -> dict:
    return {k: _mean([r[k] for r in records]) for k in ("accuracy", "completeness", "relevance")}


# ---------------------------------------------------------------------------
# Architecture snapshot
# ---------------------------------------------------------------------------


def _architecture_snapshot(notes: str) -> dict:
    chroma = PersistentClient(path=DB_PATH)
    collection = chroma.get_or_create_collection("digital_twin")
    kb_files = sorted(p.name for p in KB_DIR.glob("*.md"))
    return {
        "model": MODEL,
        "judge_model": JUDGE_MODEL,
        "embed_model": "text-embedding-3-large",
        "retrieval_k": RETRIEVAL_K,
        "final_k": FINAL_K,
        "chunk_count": collection.count(),
        "kb_file_count": len(kb_files),
        "kb_files": kb_files,
        "gap_phrase": GAP_PHRASE,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def _next_version() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    versions = []
    for p in RESULTS_DIR.glob("v*.json"):
        try:
            versions.append(int(p.stem.split("_")[0][1:]))
        except (ValueError, IndexError):
            pass
    return max(versions, default=0) + 1


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def load_tests() -> list[EvalQuestion]:
    return [
        EvalQuestion(**json.loads(line))
        for line in TESTS_PATH.read_text().splitlines()
        if line.strip()
    ]


def run_eval(notes: str = "", retrieval_only: bool = False, answer_only: bool = False) -> dict:
    tests = load_tests()
    version = _next_version()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = f"v{version}_{date}"

    print(f"\nEval run: {run_id}  ({len(tests)} questions)")
    print(f"Answer model: {MODEL}  Judge: {JUDGE_MODEL}  RETRIEVAL_K={RETRIEVAL_K}  FINAL_K={FINAL_K}")
    if notes:
        print(f"Notes: {notes}")
    print()

    per_question = []

    for i, test in enumerate(tests, 1):
        label = f"[{i:3d}/{len(tests)}] {test.category:12s}  {test.question[:55]}"
        print(f"  {label}", end="", flush=True)

        record: dict = {
            "question": test.question,
            "category": test.category,
            "keywords": test.keywords,
            "reference_answer": test.reference_answer,
        }

        parts = []

        if not answer_only:
            ret = eval_retrieval(test)
            record["retrieval"] = ret.model_dump()
            parts.append(f"MRR={ret.mrr:.2f} nDCG={ret.ndcg:.2f} cov={ret.keyword_coverage:.0f}%")

        if not retrieval_only:
            ans, generated = eval_answer(test)
            record["answer"] = {**ans.model_dump(), "generated_answer": generated}
            knew = GAP_PHRASE not in generated
            parts.append(
                f"acc={ans.accuracy:.1f} cmp={ans.completeness:.1f} rel={ans.relevance:.1f}"
                + ("" if knew else " [gap]")
            )

        print(f"  →  {' | '.join(parts)}")
        per_question.append(record)

    # --- Aggregate ---
    categories = sorted({r["category"] for r in per_question})

    result: dict = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "architecture": _architecture_snapshot(notes),
        "summary": {},
        "by_category": {},
        "per_question": per_question,
    }

    if not answer_only:
        ret_all = [r["retrieval"] for r in per_question]
        result["summary"]["retrieval"] = _agg_retrieval(ret_all)
        result["by_category"]["retrieval"] = {
            cat: _agg_retrieval([r["retrieval"] for r in per_question if r["category"] == cat])
            for cat in categories
        }

    if not retrieval_only:
        ans_all = [r["answer"] for r in per_question]
        result["summary"]["answer"] = _agg_answer(ans_all)
        result["by_category"]["answer"] = {
            cat: _agg_answer([r["answer"] for r in per_question if r["category"] == cat])
            for cat in categories
        }
        # Gap rate: fraction of questions where the system said "I don't know"
        gap_count = sum(1 for r in per_question if GAP_PHRASE in r["answer"]["generated_answer"])
        result["summary"]["gap_rate"] = round(gap_count / len(per_question), 4)

    # --- Save ---
    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(result, indent=2))

    # --- Print summary ---
    w = 62
    print(f"\n{'=' * w}")
    print(f"  Saved → {out_path.relative_to(Path(__file__).parent.parent)}")
    print(f"{'=' * w}")
    print("  SUMMARY")
    print(f"{'=' * w}")

    if "retrieval" in result["summary"]:
        r = result["summary"]["retrieval"]
        print(f"\n  Retrieval  (n={len(tests)})")
        print(f"    MRR:              {r['mrr']:.4f}  (target >0.75)")
        print(f"    nDCG:             {r['ndcg']:.4f}  (target >0.75)")
        print(f"    Keyword coverage: {r['keyword_coverage']:.1f}%")
        print(f"\n    By category:")
        for cat in categories:
            cr = result["by_category"]["retrieval"][cat]
            n = sum(1 for r in per_question if r["category"] == cat)
            print(
                f"      {cat:15s} (n={n:3d})  "
                f"MRR={cr['mrr']:.3f}  nDCG={cr['ndcg']:.3f}  cov={cr['keyword_coverage']:.0f}%"
            )

    if "answer" in result["summary"]:
        a = result["summary"]["answer"]
        gap = result["summary"]["gap_rate"]
        print(f"\n  Answer quality  (n={len(tests)})")
        print(f"    Accuracy:         {a['accuracy']:.2f}/5  (target >4.0)")
        print(f"    Completeness:     {a['completeness']:.2f}/5")
        print(f"    Relevance:        {a['relevance']:.2f}/5  (target >4.0)")
        print(f"    Gap rate:         {gap:.1%}  (questions where system said 'I don't know')")
        print(f"\n    By category:")
        for cat in categories:
            ca = result["by_category"]["answer"][cat]
            n = sum(1 for r in per_question if r["category"] == cat)
            print(
                f"      {cat:15s} (n={n:3d})  "
                f"acc={ca['accuracy']:.2f}  cmp={ca['completeness']:.2f}  rel={ca['relevance']:.2f}"
            )

    print(f"\n{'=' * w}\n")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Run digital twin RAG evaluation.")
    parser.add_argument("--notes", default="", help="Architecture notes for this run")
    parser.add_argument("--retrieval-only", action="store_true", help="Skip answer evaluation")
    parser.add_argument("--answer-only", action="store_true", help="Skip retrieval evaluation")
    args = parser.parse_args()
    run_eval(notes=args.notes, retrieval_only=args.retrieval_only, answer_only=args.answer_only)


if __name__ == "__main__":
    main()

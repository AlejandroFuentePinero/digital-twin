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
from branches import REGISTRY
from classifier import CLASSIFIER_CONFIDENCE_THRESHOLD, Classifier, ClassifierResult
from classifier import MODEL as CLASSIFIER_MODEL
from composer import PromptComposer
from generator import Generator
from profile import ProfileLoader
from retrieval import FINAL_K, MODEL, RETRIEVAL_K, fetch_context, format_context
from rules import GAP_PHRASE
from tools import ToolRegistry, build_fetch_project_readme_tool, make_litellm_tool_callable
import tool_loop

# Module-level wiring of the routed pipeline's components, reused across all
# eval questions. Tests patch these to mock the classifier and (when needed)
# the generator at the module boundary.
_classifier: Classifier = Classifier()
_profile_loader: ProfileLoader = ProfileLoader()
_composer: PromptComposer = PromptComposer(_profile_loader, REGISTRY)
_generator: Generator = Generator()
_tool_registry: ToolRegistry = ToolRegistry(
    Path(__file__).parent.parent / "data" / "readmes" / "registry.json"
)
_tool_model_callable = make_litellm_tool_callable()

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


def eval_retrieval(
    test: EvalQuestion, classification: ClassifierResult | None = None
) -> tuple[RetrievalResult, ClassifierResult]:
    """Classify (or accept pre-classified), then evaluate retrieval against the
    classifier-picked branch's `final_k`.

    `classification` may be passed in by the runner so the same routing decision
    drives both retrieval scoring and answer generation; otherwise classify here.
    """
    if classification is None:
        classification = _classifier.classify(test.question, [])
    branch_name = classification.labels[0] if classification.labels else "GENERIC"
    branch_spec = REGISTRY.get(branch_name, REGISTRY["GENERIC"])
    docs = fetch_context(test.question)[: branch_spec.final_k]
    rr = [_reciprocal_rank(kw, docs) for kw in test.keywords]
    ng = [_ndcg(kw, docs) for kw in test.keywords]
    found = sum(1 for s in rr if s > 0)
    n = len(test.keywords)
    result = RetrievalResult(
        mrr=sum(rr) / n if n else 0.0,
        ndcg=sum(ng) / n if n else 0.0,
        keywords_found=found,
        total_keywords=n,
        keyword_coverage=found / n * 100 if n else 0.0,
    )
    return result, classification


# ---------------------------------------------------------------------------
# Answer quality (LLM-as-judge)
# ---------------------------------------------------------------------------


def _generate_routed(question: str, branch_name: str) -> str:
    """Run the classify-then-route pipeline's *raw* answer path (no guardrail).

    Eval measures generated quality; guardrail rejection rates are a separate
    signal observable in the production interaction log (Sentinel). This skips
    the retry loop and the canned-refusal fallback intentionally.
    """
    branch_spec = REGISTRY.get(branch_name, REGISTRY["GENERIC"])
    chunks = fetch_context(question)[: branch_spec.final_k]
    context = format_context(chunks)
    sys_prompt = _composer.compose([branch_spec.name], "generator", retrieved_context=context)

    if branch_spec.tools:
        tool_specs = [
            build_fetch_project_readme_tool(_tool_registry)
            for tool_name in branch_spec.tools
            if tool_name == "fetch_project_readme"
        ]
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": question},
        ]
        return tool_loop.loop(_tool_model_callable, messages, tool_specs)

    return _generator.generate(sys_prompt, [], question)


# Judge system prompt is module-level so tests can pin its contract directly.
# The "ground truth = reference answer" anchor + the "cutoff" caveat were added in
# Session 27 after the v4 autopsy showed gpt-4.1 (judge) marking real-but-post-2024
# papers as fabrications because they fall outside its training data — a judge-side
# false positive that distorted the temporal-category score.
_JUDGE_SYSTEM_PROMPT = (
    "You are an expert evaluator of answer quality. "
    "Score strictly — only award 5 for a perfect answer. "
    "If any factual claim is wrong or invented, accuracy must be 1.\n\n"
    "The reference answer is the ground truth for this evaluation. Some content may be "
    "more recent than your training cutoff (e.g. 2025/2026 publications, recent roles). "
    "When the generated answer aligns with the reference, do not penalise it for content "
    "you cannot independently verify against your training data — defer to the reference. "
    "Only flag a factual error when the generated answer contradicts the reference, "
    "invents details absent from both the question and the reference, or asserts a "
    "fact you can confidently verify is wrong."
)


@retry(wait=wait, stop=stop)
def _judge(question: str, generated: str, reference: str) -> AnswerResult:
    messages = [
        {
            "role": "system",
            "content": _JUDGE_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"Generated answer:\n{generated}\n\n"
                f"Reference answer:\n{reference}\n\n"
                "Score the generated answer on three dimensions (1–5):\n"
                "- accuracy: factual correctness versus the reference answer\n"
                "- completeness: covers all information present in the reference answer\n"
                "- relevance: directly answers the question with no padding or off-topic content\n\n"
                "Provide brief feedback explaining the scores."
            ),
        },
    ]
    response = completion(model=JUDGE_MODEL, messages=messages, response_format=AnswerResult)
    return AnswerResult.model_validate_json(response.choices[0].message.content)


def eval_answer(
    test: EvalQuestion, classification: ClassifierResult | None = None
) -> tuple[AnswerResult, str, ClassifierResult]:
    """Drive the routed pipeline's raw answer path and score it with the judge.

    `classification` may be passed in by the runner so retrieval scoring and answer
    generation share one routing decision per question; otherwise classify here.

    Returns (judge result, generated answer, classifier result).
    """
    if classification is None:
        classification = _classifier.classify(test.question, [])
    branch_name = classification.labels[0] if classification.labels else "GENERIC"
    generated = _generate_routed(test.question, branch_name)
    result = _judge(test.question, generated, test.reference_answer)
    return result, generated, classification


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _agg_retrieval(records: list[dict]) -> dict:
    return {k: _mean([r[k] for r in records]) for k in ("mrr", "ndcg", "keyword_coverage")}


def _agg_answer(records: list[dict]) -> dict:
    return {k: _mean([r[k] for r in records]) for k in ("accuracy", "completeness", "relevance")}


def _cross_tab(per_question: list[dict], retrieval_only: bool, answer_only: bool) -> dict:
    """Sparse {category: {branch: {retrieval, answer}}} nested aggregation.

    Only (category, branch) pairs that actually appeared in the run get an
    entry. A regression in a category may show up here as a redistribution
    across branches rather than a true quality drop — read alongside
    `by_category` and `by_branch`.
    """
    out: dict[str, dict[str, dict]] = {}
    for r in per_question:
        cat = r["category"]
        branch = r.get("branch")
        if branch is None:
            continue
        cell = out.setdefault(cat, {}).setdefault(branch, {})
        if not answer_only and "retrieval" in r:
            cell.setdefault("_retrieval_records", []).append(r["retrieval"])
        if not retrieval_only and "answer" in r:
            cell.setdefault("_answer_records", []).append(r["answer"])
    for cat, by_branch in out.items():
        for branch, cell in by_branch.items():
            if "_retrieval_records" in cell:
                cell["retrieval"] = _agg_retrieval(cell.pop("_retrieval_records"))
            if "_answer_records" in cell:
                cell["answer"] = _agg_answer(cell.pop("_answer_records"))
    return out


# ---------------------------------------------------------------------------
# Architecture snapshot
# ---------------------------------------------------------------------------


def _architecture_snapshot(notes: str) -> dict:
    chroma = PersistentClient(path=DB_PATH)
    collection = chroma.get_or_create_collection("digital_twin")
    kb_files = sorted(p.name for p in KB_DIR.glob("*.md"))
    branches = {
        name: {
            "final_k": spec.final_k,
            "tools": list(spec.tools),
            "profile_sections": list(spec.profile_sections),
        }
        for name, spec in REGISTRY.items()
    }
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
        "classifier_model": CLASSIFIER_MODEL,
        "branches": branches,
        "routing_in_loop": True,
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

        # Classify once per question. Both retrieval scoring and answer generation
        # use the same branch — without this, a borderline question can route to
        # different branches between stages and the per-question record's `branch`
        # no longer matches what produced the answer.
        classification = _classifier.classify(test.question, [])
        record["branch"] = classification.labels[0] if classification.labels else "GENERIC"
        record["classification_confidence"] = classification.confidence
        record["secondary_branch"] = (
            classification.labels[1] if len(classification.labels) > 1 else None
        )

        parts = []

        if not answer_only:
            ret, _ = eval_retrieval(test, classification)
            record["retrieval"] = ret.model_dump()
            parts.append(f"MRR={ret.mrr:.2f} nDCG={ret.ndcg:.2f} cov={ret.keyword_coverage:.0f}%")

        if not retrieval_only:
            ans, generated, _ = eval_answer(test, classification)
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
    branches = sorted({r["branch"] for r in per_question if "branch" in r})

    result: dict = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "architecture": _architecture_snapshot(notes),
        "summary": {},
        "by_category": {},
        "by_branch": {},
        "cross_tab": _cross_tab(
            per_question, retrieval_only=retrieval_only, answer_only=answer_only,
        ),
        "per_question": per_question,
    }

    if not answer_only:
        ret_all = [r["retrieval"] for r in per_question]
        result["summary"]["retrieval"] = _agg_retrieval(ret_all)
        result["by_category"]["retrieval"] = {
            cat: _agg_retrieval([r["retrieval"] for r in per_question if r["category"] == cat])
            for cat in categories
        }
        result["by_branch"]["retrieval"] = {
            br: _agg_retrieval([r["retrieval"] for r in per_question if r.get("branch") == br])
            for br in branches
        }

    # Classifier low-confidence count is independent of retrieval/answer skip flags —
    # it's a routing-quality signal computed from per-question classification fields.
    confidences = [r["classification_confidence"] for r in per_question if "classification_confidence" in r]
    result["summary"]["classifier_low_confidence_count"] = sum(
        1 for c in confidences if c < CLASSIFIER_CONFIDENCE_THRESHOLD
    )

    if not retrieval_only:
        ans_all = [r["answer"] for r in per_question]
        result["summary"]["answer"] = _agg_answer(ans_all)
        result["by_category"]["answer"] = {
            cat: _agg_answer([r["answer"] for r in per_question if r["category"] == cat])
            for cat in categories
        }
        result["by_branch"]["answer"] = {
            br: _agg_answer([r["answer"] for r in per_question if r.get("branch") == br])
            for br in branches
        }
        # Gap rate: fraction of questions where the system said "I don't know"
        gap_count = sum(1 for r in per_question if GAP_PHRASE in r["answer"]["generated_answer"])
        result["summary"]["gap_rate"] = round(gap_count / len(per_question), 4)

    # --- Save ---
    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(result, indent=2))

    # --- Print summary ---
    w = 62
    project_root = Path(__file__).parent.parent
    try:
        display_path = out_path.relative_to(project_root)
    except ValueError:
        display_path = out_path  # tmp_path or other off-project location (tests)
    print(f"\n{'=' * w}")
    print(f"  Saved → {display_path}")
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
        if branches:
            print(f"\n    By branch:")
            for br in branches:
                br_metrics = result["by_branch"]["retrieval"][br]
                n = sum(1 for r in per_question if r.get("branch") == br)
                print(
                    f"      {br:15s} (n={n:3d})  "
                    f"MRR={br_metrics['mrr']:.3f}  nDCG={br_metrics['ndcg']:.3f}  cov={br_metrics['keyword_coverage']:.0f}%"
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
        if branches:
            print(f"\n    By branch:")
            for br in branches:
                ba = result["by_branch"]["answer"][br]
                n = sum(1 for r in per_question if r.get("branch") == br)
                print(
                    f"      {br:15s} (n={n:3d})  "
                    f"acc={ba['accuracy']:.2f}  cmp={ba['completeness']:.2f}  rel={ba['relevance']:.2f}"
                )

    low_conf = result["summary"].get("classifier_low_confidence_count", 0)
    print(f"\n  Routing")
    print(f"    Low-confidence classifications: {low_conf}/{len(tests)}  "
          f"(threshold {CLASSIFIER_CONFIDENCE_THRESHOLD})")

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

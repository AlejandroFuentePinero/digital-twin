"""
Tests for eval/run_eval.py.

Strategy:
- Metric functions (_reciprocal_rank, _ndcg, _dcg): pure, no mocks needed
- Aggregation helpers: pure
- next_version: filesystem interaction — use tmp_path
- load_tests: filesystem — use tmp_path
- eval_retrieval / eval_answer: mock at the I/O boundary (fetch_context, completion)
"""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# run_eval.py lives in eval/, not src/ — add eval/ to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))
import run_eval as E  # adds src/ to sys.path on import — must be before classifier import
from run_eval import (
    AnswerResult,
    RetrievalResult,
    EvalQuestion,
    _agg_answer,
    _agg_retrieval,
    _dcg,
    _mean,
    _ndcg,
    _next_version,
    _reciprocal_rank,
    eval_answer,
    eval_retrieval,
    load_tests,
)
from classifier import ClassifierResult


def make_doc(content: str, metadata: dict | None = None):
    """Stand-in for retrieval.Chunk — exposes both the page_content (read by
    eval metrics) and the metadata dict (read by retrieval.format_context)."""
    return SimpleNamespace(
        page_content=content,
        metadata=metadata or {"source_file": "stub.md", "section_heading": "stub"},
    )


def make_test(**kwargs) -> EvalQuestion:
    defaults = dict(
        question="What is his PhD topic?",
        keywords=["ecology", "JCU"],
        reference_answer="Tropical ecology at JCU.",
        category="direct_fact",
    )
    return EvalQuestion(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# _reciprocal_rank
# ---------------------------------------------------------------------------


def test_rr_returns_1_when_keyword_in_first_doc():
    """Reciprocal rank is 1.0 when the keyword hits the top-ranked doc."""
    docs = [make_doc("ecology methods"), make_doc("other content")]
    assert _reciprocal_rank("ecology", docs) == 1.0


def test_rr_returns_half_when_keyword_in_second_doc():
    """Reciprocal rank is 0.5 when the keyword first appears at rank 2."""
    docs = [make_doc("other content"), make_doc("ecology methods")]
    assert _reciprocal_rank("ecology", docs) == pytest.approx(0.5)


def test_rr_returns_zero_when_keyword_not_found():
    """Reciprocal rank is 0.0 when no retrieved doc contains the keyword."""
    docs = [make_doc("statistics"), make_doc("modelling")]
    assert _reciprocal_rank("ecology", docs) == 0.0


def test_rr_is_case_insensitive():
    """Reciprocal rank ignores keyword/document casing."""
    docs = [make_doc("ECOLOGY methods")]
    assert _reciprocal_rank("ecology", docs) == 1.0


def test_rr_returns_zero_for_empty_docs():
    """Reciprocal rank degrades gracefully to 0.0 on empty retrieval."""
    assert _reciprocal_rank("ecology", []) == 0.0


# ---------------------------------------------------------------------------
# _dcg
# ---------------------------------------------------------------------------


def test_dcg_with_single_relevant_at_rank_1():
    """DCG=1.0 when the relevant doc is at rank 1 (1/log2(2))."""
    assert _dcg([1], k=1) == pytest.approx(1.0)


def test_dcg_with_single_relevant_at_rank_2():
    """DCG discounts a relevant doc at rank 2 by 1/log2(3)."""
    assert _dcg([0, 1], k=2) == pytest.approx(1.0 / math.log2(3))


def test_dcg_with_all_zeros():
    """DCG is 0.0 when no doc is relevant."""
    assert _dcg([0, 0, 0], k=3) == 0.0


def test_dcg_respects_k_cutoff():
    """Only the first k positions contribute to DCG; later relevance is ignored."""
    assert _dcg([0, 0, 1], k=2) == 0.0


# ---------------------------------------------------------------------------
# _ndcg
# ---------------------------------------------------------------------------


def test_ndcg_is_1_when_keyword_in_first_doc():
    """nDCG saturates at 1.0 when retrieval is perfect."""
    docs = [make_doc("ecology methods")]
    assert _ndcg("ecology", docs, k=1) == pytest.approx(1.0)


def test_ndcg_is_0_when_keyword_absent():
    """nDCG is 0.0 when no retrieved doc is relevant."""
    docs = [make_doc("statistics"), make_doc("modelling")]
    assert _ndcg("ecology", docs, k=2) == 0.0


def test_ndcg_is_less_than_1_when_keyword_not_at_rank_1():
    """nDCG penalises late-rank relevance (<1.0 but >0.0)."""
    docs = [make_doc("other"), make_doc("ecology found here")]
    score = _ndcg("ecology", docs, k=2)
    assert 0.0 < score < 1.0


def test_ndcg_returns_0_for_empty_docs():
    """nDCG degrades gracefully to 0.0 on empty retrieval."""
    assert _ndcg("ecology", [], k=5) == 0.0


# ---------------------------------------------------------------------------
# _mean
# ---------------------------------------------------------------------------


def test_mean_of_values():
    """_mean returns the arithmetic mean of a non-empty sequence."""
    assert _mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_mean_of_empty_list_is_zero():
    """_mean returns 0.0 for an empty sequence rather than raising."""
    assert _mean([]) == 0.0


def test_mean_rounds_to_4_decimal_places():
    """_mean is rounded to 4 decimal places for stable result-file diffs."""
    result = _mean([1.0 / 3.0])
    assert result == pytest.approx(0.3333, abs=1e-4)


# ---------------------------------------------------------------------------
# _agg_retrieval and _agg_answer
# ---------------------------------------------------------------------------


def test_agg_retrieval_averages_across_records():
    """_agg_retrieval averages mrr/ndcg/keyword_coverage across all eval records."""
    records = [
        {"mrr": 0.5, "ndcg": 0.6, "keyword_coverage": 80.0},
        {"mrr": 1.0, "ndcg": 0.8, "keyword_coverage": 100.0},
    ]
    result = _agg_retrieval(records)
    assert result["mrr"] == pytest.approx(0.75)
    assert result["ndcg"] == pytest.approx(0.7)
    assert result["keyword_coverage"] == pytest.approx(90.0)


def test_agg_answer_averages_across_records():
    """_agg_answer averages accuracy/completeness/relevance across all eval records."""
    records = [
        {"accuracy": 4.0, "completeness": 3.0, "relevance": 5.0},
        {"accuracy": 2.0, "completeness": 5.0, "relevance": 3.0},
    ]
    result = _agg_answer(records)
    assert result["accuracy"] == pytest.approx(3.0)
    assert result["completeness"] == pytest.approx(4.0)
    assert result["relevance"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# _next_version
# ---------------------------------------------------------------------------


def test_next_version_returns_1_when_no_results_exist(tmp_path, monkeypatch):
    """_next_version starts at 1 when no eval results have been written yet."""
    monkeypatch.setattr(E, "RESULTS_DIR", tmp_path)
    assert _next_version() == 1


def test_next_version_increments_from_existing(tmp_path, monkeypatch):
    """_next_version returns one above the highest existing v<N> result file."""
    monkeypatch.setattr(E, "RESULTS_DIR", tmp_path)
    (tmp_path / "v1_2026-04-28.json").write_text("{}")
    (tmp_path / "v2_2026-04-29.json").write_text("{}")
    assert _next_version() == 3


def test_next_version_ignores_non_versioned_files(tmp_path, monkeypatch):
    """_next_version ignores files that don't match the v<N>_ pattern."""
    monkeypatch.setattr(E, "RESULTS_DIR", tmp_path)
    (tmp_path / "README.md").write_text("notes")
    assert _next_version() == 1


# ---------------------------------------------------------------------------
# load_tests
# ---------------------------------------------------------------------------


def test_load_tests_parses_jsonl(tmp_path, monkeypatch):
    """load_tests parses each JSONL line into an EvalQuestion."""
    lines = [
        json.dumps({"question": "q1", "keywords": ["k1"], "reference_answer": "a1", "category": "direct_fact"}),
        json.dumps({"question": "q2", "keywords": ["k2"], "reference_answer": "a2", "category": "temporal"}),
    ]
    f = tmp_path / "tests.jsonl"
    f.write_text("\n".join(lines))
    monkeypatch.setattr(E, "TESTS_PATH", f)

    tests = load_tests()
    assert len(tests) == 2
    assert tests[0].question == "q1"
    assert tests[1].category == "temporal"


def test_load_tests_skips_blank_lines(tmp_path, monkeypatch):
    """load_tests is tolerant of blank lines in the eval JSONL file."""
    line = json.dumps({"question": "q", "keywords": [], "reference_answer": "a", "category": "holistic"})
    f = tmp_path / "tests.jsonl"
    f.write_text(f"{line}\n\n{line}\n")
    monkeypatch.setattr(E, "TESTS_PATH", f)

    tests = load_tests()
    assert len(tests) == 2


# ---------------------------------------------------------------------------
# eval_retrieval — integration shape (mocked fetch_context + classifier)
# ---------------------------------------------------------------------------


def _stub_classifier(labels=None, confidence=0.9):
    """Build a Classifier stub that returns a fixed ClassifierResult on .classify()."""
    cls = MagicMock()
    cls.classify.return_value = ClassifierResult(
        labels=labels or ["GENERIC"], confidence=confidence
    )
    return cls


def test_eval_retrieval_returns_retrieval_result_and_classification():
    """eval_retrieval returns (RetrievalResult, ClassifierResult) so the runner can
    record which branch the classifier picked alongside retrieval metrics."""
    docs = [make_doc("ecology methods"), make_doc("JCU research")]
    test = make_test(keywords=["ecology", "JCU"])
    with patch("run_eval.fetch_context", return_value=docs), \
         patch.object(E, "_classifier", _stub_classifier(labels=["GENERIC"], confidence=0.92)):
        result, classification = eval_retrieval(test)
    assert isinstance(result, RetrievalResult)
    assert isinstance(classification, ClassifierResult)
    assert result.total_keywords == 2
    assert result.keywords_found == 2
    assert classification.labels == ["GENERIC"]
    assert classification.confidence == pytest.approx(0.92)


def test_eval_retrieval_keyword_coverage_is_percentage():
    """keyword_coverage is reported as a percentage (50.0 not 0.5) for dashboard readability."""
    docs = [make_doc("ecology content")]
    test = make_test(keywords=["ecology", "JCU"])
    with patch("run_eval.fetch_context", return_value=docs), \
         patch.object(E, "_classifier", _stub_classifier()):
        result, _ = eval_retrieval(test)
    assert result.keyword_coverage == pytest.approx(50.0)
    assert result.keywords_found == 1


def test_eval_retrieval_zero_when_no_keywords_found():
    """All retrieval metrics collapse to 0.0 when no keywords are found."""
    docs = [make_doc("unrelated content")]
    test = make_test(keywords=["ecology", "JCU"])
    with patch("run_eval.fetch_context", return_value=docs), \
         patch.object(E, "_classifier", _stub_classifier()):
        result, _ = eval_retrieval(test)
    assert result.mrr == 0.0
    assert result.ndcg == 0.0
    assert result.keyword_coverage == 0.0


# ---------------------------------------------------------------------------
# eval_answer — routed-pipeline integration shape
# ---------------------------------------------------------------------------


def _stub_judge_response(accuracy=4.0, completeness=4.0, relevance=4.0, feedback="ok"):
    """Build a litellm completion-style response carrying an AnswerResult JSON."""
    payload = AnswerResult(
        accuracy=accuracy, completeness=completeness, relevance=relevance, feedback=feedback,
    ).model_dump_json()
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


# ---------------------------------------------------------------------------
# run_eval — end-to-end record + aggregation shape
# ---------------------------------------------------------------------------


def _writeable_results_dir(tmp_path):
    """Return a tmp_path for RESULTS_DIR so run_eval doesn't pollute eval/results/."""
    d = tmp_path / "results"
    d.mkdir()
    return d


def _stub_arch_snapshot(notes=""):
    return {"notes": notes, "model": "stub", "branches": {}, "classifier_model": "stub", "routing_in_loop": True}


def _run_eval_with_stubs(tmp_path, monkeypatch, *, classifications, retrieval_results=None,
                        answers=None, judge=None):
    """Drive run_eval with all I/O boundaries mocked.

    `classifications` is a list of ClassifierResult, one per test question.
    Returns the full result dict.
    """
    n = len(classifications)
    retrieval_results = retrieval_results or [
        RetrievalResult(mrr=0.5, ndcg=0.5, keywords_found=1, total_keywords=1, keyword_coverage=100.0)
        for _ in range(n)
    ]
    answers = answers or [
        (AnswerResult(accuracy=4.0, completeness=4.0, relevance=4.0, feedback="ok"), "Generated answer", classifications[i])
        for i in range(n)
    ]

    # Build a synthetic tests.jsonl with `n` questions.
    lines = [
        json.dumps({
            "question": f"q{i}",
            "keywords": ["kw"],
            "reference_answer": f"ref{i}",
            "category": "direct_fact" if i % 2 == 0 else "temporal",
        })
        for i in range(n)
    ]
    f = tmp_path / "tests.jsonl"
    f.write_text("\n".join(lines))
    monkeypatch.setattr(E, "TESTS_PATH", f)
    monkeypatch.setattr(E, "RESULTS_DIR", _writeable_results_dir(tmp_path))
    monkeypatch.setattr(E, "_architecture_snapshot", _stub_arch_snapshot)

    # run_eval classifies once per question at the top of the main loop, then
    # passes the result into eval_retrieval/eval_answer. Stub all three layers.
    classifier_iter = iter(classifications)
    monkeypatch.setattr(
        E, "_classifier", MagicMock(classify=lambda q, h: next(classifier_iter))
    )
    eval_retrieval_calls = iter(zip(retrieval_results, classifications))
    eval_answer_calls = iter(answers)
    monkeypatch.setattr(E, "eval_retrieval", lambda test, classification: next(eval_retrieval_calls))
    monkeypatch.setattr(E, "eval_answer", lambda test, classification: next(eval_answer_calls))

    return E.run_eval()


def test_run_eval_by_branch_aggregates_separately_from_categories(tmp_path, monkeypatch):
    """`by_branch` mirrors `by_category` — averages retrieval + answer metrics across
    questions sharing a branch label, not a category label."""
    classifications = [
        ClassifierResult(labels=["GAP"], confidence=0.9),
        ClassifierResult(labels=["GAP"], confidence=0.8),
        ClassifierResult(labels=["TECHNICAL"], confidence=0.95),
    ]
    retrieval_results = [
        RetrievalResult(mrr=0.4, ndcg=0.4, keywords_found=1, total_keywords=1, keyword_coverage=100.0),
        RetrievalResult(mrr=0.6, ndcg=0.6, keywords_found=1, total_keywords=1, keyword_coverage=100.0),
        RetrievalResult(mrr=1.0, ndcg=1.0, keywords_found=1, total_keywords=1, keyword_coverage=100.0),
    ]
    answers = [
        (AnswerResult(accuracy=3.0, completeness=3.0, relevance=3.0, feedback="ok"), "ans0", classifications[0]),
        (AnswerResult(accuracy=4.0, completeness=4.0, relevance=4.0, feedback="ok"), "ans1", classifications[1]),
        (AnswerResult(accuracy=5.0, completeness=5.0, relevance=5.0, feedback="ok"), "ans2", classifications[2]),
    ]
    result = _run_eval_with_stubs(
        tmp_path, monkeypatch,
        classifications=classifications, retrieval_results=retrieval_results, answers=answers,
    )
    assert "by_branch" in result
    gap = result["by_branch"]["retrieval"]["GAP"]
    tech = result["by_branch"]["retrieval"]["TECHNICAL"]
    assert gap["mrr"] == pytest.approx(0.5)        # mean of 0.4 and 0.6
    assert tech["mrr"] == pytest.approx(1.0)       # only one TECHNICAL question
    gap_ans = result["by_branch"]["answer"]["GAP"]
    assert gap_ans["accuracy"] == pytest.approx(3.5)


def test_run_eval_cross_tab_only_filled_where_data_exists(tmp_path, monkeypatch):
    """`cross_tab` is a {category: {branch: metrics}} nested dict; only (category, branch)
    pairs that actually appeared in the run get an entry — sparse, no zero-filled cells."""
    # Synthetic tests use direct_fact (i%2==0) and temporal (i%2==1).
    # Branches: q0=GAP, q1=TECHNICAL, q2=GAP — so direct_fact has GAP twice (q0, q2),
    # temporal has TECHNICAL once (q1). direct_fact × TECHNICAL and temporal × GAP are
    # *never observed* and should be absent from the cross-tab.
    classifications = [
        ClassifierResult(labels=["GAP"], confidence=0.9),
        ClassifierResult(labels=["TECHNICAL"], confidence=0.9),
        ClassifierResult(labels=["GAP"], confidence=0.9),
    ]
    result = _run_eval_with_stubs(tmp_path, monkeypatch, classifications=classifications)
    cross_tab = result["cross_tab"]
    # Observed cells are present
    assert "retrieval" in cross_tab["direct_fact"]["GAP"]
    assert "answer" in cross_tab["direct_fact"]["GAP"]
    assert "retrieval" in cross_tab["temporal"]["TECHNICAL"]
    # Unobserved cells are absent
    assert "TECHNICAL" not in cross_tab["direct_fact"]
    assert "GAP" not in cross_tab["temporal"]


def test_judge_prompt_acknowledges_post_cutoff_content():
    """The judge's system prompt must acknowledge that some KB content may post-date its
    training cutoff (e.g. 2025/2026 publications) and must score against the reference
    answer, not against what it can independently verify.

    Surfaced by v4 eval (Session 27 / #2 autopsy): the judge (gpt-4.1) flagged real
    post-2024 papers as 'no such paper exists' purely because they fall outside its
    training data — turning a valid system answer into accuracy=1. The reference answer
    is ground truth; the judge must defer to it on verifiability questions.
    """
    judge_prompt = E._JUDGE_SYSTEM_PROMPT.lower()
    # Must mention training cutoff or recent content explicitly
    assert "cutoff" in judge_prompt or "training" in judge_prompt or "more recent" in judge_prompt, \
        "judge prompt must acknowledge that KB content may post-date its training data"
    # Must direct the judge to use the reference answer as ground truth
    assert "reference" in judge_prompt and "ground truth" in judge_prompt, \
        "judge prompt must explicitly anchor scoring to the reference answer as ground truth"


def test_architecture_snapshot_records_routing_config():
    """The architecture snapshot in the result file records the routing config so v4
    runs are reproducible: branches with their final_k/tools/profile_sections, the
    classifier model, and a routing_in_loop flag."""
    snap = E._architecture_snapshot("test notes")
    assert snap["routing_in_loop"] is True
    assert snap["classifier_model"] == E.CLASSIFIER_MODEL
    assert "branches" in snap
    # Spot-check one branch's structure rather than enumerating all five — keeps the
    # test resilient to future branch additions.
    gap = snap["branches"]["GAP"]
    assert "final_k" in gap and "tools" in gap and "profile_sections" in gap


def test_run_eval_classifier_low_confidence_count_counts_below_threshold(tmp_path, monkeypatch):
    """`summary.classifier_low_confidence_count` is the count of questions where the
    classifier's reported confidence fell below CLASSIFIER_CONFIDENCE_THRESHOLD."""
    from classifier import CLASSIFIER_CONFIDENCE_THRESHOLD as T
    classifications = [
        ClassifierResult(labels=["GENERIC"], confidence=T - 0.1),  # low
        ClassifierResult(labels=["GAP"], confidence=T + 0.2),       # high
        ClassifierResult(labels=["GENERIC"], confidence=T - 0.2),  # low
    ]
    result = _run_eval_with_stubs(tmp_path, monkeypatch, classifications=classifications)
    assert result["summary"]["classifier_low_confidence_count"] == 2


def test_run_eval_per_question_record_carries_branch_and_confidence(tmp_path, monkeypatch):
    """Each per-question record carries the classifier-picked branch, confidence,
    and (when classifier returned 2 labels) a secondary branch."""
    classifications = [
        ClassifierResult(labels=["GAP"], confidence=0.81),
        ClassifierResult(labels=["TECHNICAL", "GENERIC"], confidence=0.73),
    ]
    result = _run_eval_with_stubs(tmp_path, monkeypatch, classifications=classifications)
    pq = result["per_question"]
    assert pq[0]["branch"] == "GAP"
    assert pq[0]["classification_confidence"] == pytest.approx(0.81)
    assert pq[0]["secondary_branch"] is None
    assert pq[1]["branch"] == "TECHNICAL"
    assert pq[1]["secondary_branch"] == "GENERIC"


def test_eval_answer_returns_answer_result_generated_and_classification():
    """eval_answer drives the routed pipeline (no guardrail) and surfaces the classifier
    result so the runner can record per-question branch metadata."""
    docs = [make_doc("ecology methods at JCU")]
    test = make_test(keywords=["ecology"])
    # BEHAVIOURAL has tools=[] so eval_answer takes the bare-generator path —
    # the test stubs _generator.generate, not the tool model callable. (Post-
    # Session 56 the tool is also available in TECHNICAL/GAP/GENERIC; staying
    # on BEHAVIOURAL keeps this test focused on the non-tool dispatch path.)
    cls = _stub_classifier(labels=["BEHAVIOURAL"], confidence=0.88)
    gen = MagicMock()
    gen.generate.return_value = "Alejandro did tropical ecology at JCU."
    with patch("run_eval.fetch_context", return_value=docs), \
         patch("run_eval.completion", return_value=_stub_judge_response(accuracy=4.5)), \
         patch.object(E, "_classifier", cls), \
         patch.object(E, "_generator", gen):
        ans, generated, classification = eval_answer(test)
    assert isinstance(ans, AnswerResult)
    assert isinstance(classification, ClassifierResult)
    assert generated == "Alejandro did tropical ecology at JCU."
    assert classification.labels == ["BEHAVIOURAL"]
    assert ans.accuracy == pytest.approx(4.5)

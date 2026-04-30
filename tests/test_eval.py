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
import run_eval as E
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
    eval_retrieval,
    load_tests,
)


def make_doc(content: str):
    return SimpleNamespace(page_content=content)


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
    docs = [make_doc("ecology methods"), make_doc("other content")]
    assert _reciprocal_rank("ecology", docs) == 1.0


def test_rr_returns_half_when_keyword_in_second_doc():
    docs = [make_doc("other content"), make_doc("ecology methods")]
    assert _reciprocal_rank("ecology", docs) == pytest.approx(0.5)


def test_rr_returns_zero_when_keyword_not_found():
    docs = [make_doc("statistics"), make_doc("modelling")]
    assert _reciprocal_rank("ecology", docs) == 0.0


def test_rr_is_case_insensitive():
    docs = [make_doc("ECOLOGY methods")]
    assert _reciprocal_rank("ecology", docs) == 1.0


def test_rr_returns_zero_for_empty_docs():
    assert _reciprocal_rank("ecology", []) == 0.0


# ---------------------------------------------------------------------------
# _dcg
# ---------------------------------------------------------------------------


def test_dcg_with_single_relevant_at_rank_1():
    # dcg = 1 / log2(2) = 1.0
    assert _dcg([1], k=1) == pytest.approx(1.0)


def test_dcg_with_single_relevant_at_rank_2():
    # dcg = 0 + 1/log2(3)
    assert _dcg([0, 1], k=2) == pytest.approx(1.0 / math.log2(3))


def test_dcg_with_all_zeros():
    assert _dcg([0, 0, 0], k=3) == 0.0


def test_dcg_respects_k_cutoff():
    # Only first k items count
    assert _dcg([0, 0, 1], k=2) == 0.0


# ---------------------------------------------------------------------------
# _ndcg
# ---------------------------------------------------------------------------


def test_ndcg_is_1_when_keyword_in_first_doc():
    docs = [make_doc("ecology methods")]
    assert _ndcg("ecology", docs, k=1) == pytest.approx(1.0)


def test_ndcg_is_0_when_keyword_absent():
    docs = [make_doc("statistics"), make_doc("modelling")]
    assert _ndcg("ecology", docs, k=2) == 0.0


def test_ndcg_is_less_than_1_when_keyword_not_at_rank_1():
    docs = [make_doc("other"), make_doc("ecology found here")]
    score = _ndcg("ecology", docs, k=2)
    assert 0.0 < score < 1.0


def test_ndcg_returns_0_for_empty_docs():
    assert _ndcg("ecology", [], k=5) == 0.0


# ---------------------------------------------------------------------------
# _mean
# ---------------------------------------------------------------------------


def test_mean_of_values():
    assert _mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_mean_of_empty_list_is_zero():
    assert _mean([]) == 0.0


def test_mean_rounds_to_4_decimal_places():
    result = _mean([1.0 / 3.0])
    assert result == pytest.approx(0.3333, abs=1e-4)


# ---------------------------------------------------------------------------
# _agg_retrieval and _agg_answer
# ---------------------------------------------------------------------------


def test_agg_retrieval_averages_across_records():
    records = [
        {"mrr": 0.5, "ndcg": 0.6, "keyword_coverage": 80.0},
        {"mrr": 1.0, "ndcg": 0.8, "keyword_coverage": 100.0},
    ]
    result = _agg_retrieval(records)
    assert result["mrr"] == pytest.approx(0.75)
    assert result["ndcg"] == pytest.approx(0.7)
    assert result["keyword_coverage"] == pytest.approx(90.0)


def test_agg_answer_averages_across_records():
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
    monkeypatch.setattr(E, "RESULTS_DIR", tmp_path)
    assert _next_version() == 1


def test_next_version_increments_from_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RESULTS_DIR", tmp_path)
    (tmp_path / "v1_2026-04-28.json").write_text("{}")
    (tmp_path / "v2_2026-04-29.json").write_text("{}")
    assert _next_version() == 3


def test_next_version_ignores_non_versioned_files(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RESULTS_DIR", tmp_path)
    (tmp_path / "README.md").write_text("notes")
    assert _next_version() == 1


# ---------------------------------------------------------------------------
# load_tests
# ---------------------------------------------------------------------------


def test_load_tests_parses_jsonl(tmp_path, monkeypatch):
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
    line = json.dumps({"question": "q", "keywords": [], "reference_answer": "a", "category": "holistic"})
    f = tmp_path / "tests.jsonl"
    f.write_text(f"{line}\n\n{line}\n")
    monkeypatch.setattr(E, "TESTS_PATH", f)

    tests = load_tests()
    assert len(tests) == 2


# ---------------------------------------------------------------------------
# eval_retrieval — integration shape (mocked fetch_context)
# ---------------------------------------------------------------------------


def test_eval_retrieval_returns_retrieval_result():
    docs = [make_doc("ecology methods"), make_doc("JCU research")]
    test = make_test(keywords=["ecology", "JCU"])
    with patch("run_eval.fetch_context", return_value=docs):
        result = eval_retrieval(test)
    assert isinstance(result, RetrievalResult)
    assert result.total_keywords == 2
    assert result.keywords_found == 2


def test_eval_retrieval_keyword_coverage_is_percentage():
    docs = [make_doc("ecology content")]  # only first keyword found
    test = make_test(keywords=["ecology", "JCU"])
    with patch("run_eval.fetch_context", return_value=docs):
        result = eval_retrieval(test)
    assert result.keyword_coverage == pytest.approx(50.0)
    assert result.keywords_found == 1


def test_eval_retrieval_zero_when_no_keywords_found():
    docs = [make_doc("unrelated content")]
    test = make_test(keywords=["ecology", "JCU"])
    with patch("run_eval.fetch_context", return_value=docs):
        result = eval_retrieval(test)
    assert result.mrr == 0.0
    assert result.ndcg == 0.0
    assert result.keyword_coverage == 0.0

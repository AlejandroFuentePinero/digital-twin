"""Every OpenAI chat call site sends its tier's gpt-6 model with reasoning off (#55).

Each site is driven through its public function with the provider call mocked
at the boundary; the assertion is on the request that would leave the process.
Model names are the #55 selection: gpt-6.1-terra for the generator tier,
gpt-6-luna for the cheap tier.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from interaction_log import InteractionRecord

TERRA = "openai/gpt-6.1-terra"
LUNA = "openai/gpt-6-luna"
EXPECTED_EXTRA_BODY = {"reasoning_effort": "none"}


def _reply(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
    )


def _gap_record() -> InteractionRecord:
    return InteractionRecord.model_validate(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": "s",
            "turn_index": 0,
            "question": "Have you used AWS?",
            "event_type": "gap",
            "branch": "GAP",
            "classification_confidence": 0.9,
            "attempts": [{"answer": "a", "is_acceptable": True, "guardrail_feedback": ""}],
            "retrieved_chunks": [],
            "tool_calls": [],
            "latency_ms": {"classifier": 0, "retrieval": 0, "generation": 0, "guardrail": 0, "total": 0},
            "knew_answer": False,
        }
    )


def _classify():
    from classifier import Classifier

    Classifier().classify("Do you know AWS?", [])


def _generate():
    from generator import Generator

    Generator().generate("system", [], "question")


def _rewrite():
    from retrieval import rewrite_query

    rewrite_query("Do you know AWS?")


def _rerank():
    from retrieval import Chunk, rerank

    rerank("q", [Chunk(page_content="a", metadata={})])


def _tool_loop():
    from tools import make_litellm_tool_callable

    make_litellm_tool_callable()([{"role": "user", "content": "q"}], [])


def _cluster():
    from cluster_gaps import GapClusterer

    GapClusterer().cluster(["Have you used AWS?"])


def _summarize():
    from summarize_failures import FailureSummarizer

    FailureSummarizer().summarize([_gap_record()], group="gap", period_days=7)


CALL_SITES = [
    ("classifier", "classifier.completion", _classify, LUNA, '{"labels":["GENERIC"],"confidence":0.9}'),
    ("generator", "generator.completion", _generate, TERRA, "answer"),
    ("query rewrite", "retrieval.completion", _rewrite, LUNA, "aws experience"),
    ("rerank", "retrieval.completion", _rerank, TERRA, '{"order":[1]}'),
    ("tool loop", "tools.completion", _tool_loop, TERRA, "answer"),
    ("gap clusterer", "cluster_gaps.completion", _cluster, LUNA, '{"clusters":[]}'),
    ("failure summariser", "summarize_failures.completion", _summarize, TERRA, "## Summary"),
]


@pytest.mark.parametrize(
    "target, call, model, content",
    [site[1:] for site in CALL_SITES],
    ids=[site[0] for site in CALL_SITES],
)
def test_litellm_call_site_sends_its_tier_model_with_reasoning_off(target, call, model, content):
    """Each LiteLLM call site requests its tier's gpt-6 model with reasoning_effort "none" in extra_body."""
    with patch(target, return_value=_reply(content)) as mock:
        call()

    kwargs = mock.call_args.kwargs
    assert kwargs["model"] == model
    assert kwargs["extra_body"] == EXPECTED_EXTRA_BODY


def test_ingest_enrichment_sends_luna_with_reasoning_off():
    """Chunk enrichment at ingest (OpenAI SDK, not LiteLLM) requests gpt-6-luna with reasoning_effort "none"."""
    from ingest import ChunkEnrichment, enrich_chunk

    response = MagicMock()
    response.choices[0].message.parsed = ChunkEnrichment(headline="h?", summary="s.")
    chunk = {"text": "t", "section_heading": "S", "heading_level": 2, "source_file": "f.md", "category": "c"}
    with patch("ingest.client.beta.chat.completions.parse", return_value=response) as mock:
        enrich_chunk(chunk)

    kwargs = mock.call_args.kwargs
    assert kwargs["model"] == "gpt-6-luna"
    assert kwargs["extra_body"] == EXPECTED_EXTRA_BODY

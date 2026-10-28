"""Tests for the startup model probe (#57).

The probe runs once at app start, before the chat serves, and makes one minimal
call per configured model. All provider calls are mocked at the boundary
(`startup_probe.completion`, `startup_probe.OpenAI`); no test here reaches a
real API.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import litellm
import pytest

from startup_probe import ModelProbe, StartupProbeError, run_startup_probe


def _ok_completion(*_args, **_kwargs):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )


def test_missing_model_fails_startup_naming_stage_and_model():
    """A NotFoundError from one model raises StartupProbeError whose message names that stage and model."""
    probes = [
        ModelProbe(stage="classifier", model="openai/gpt-4.1-mini"),
        ModelProbe(stage="guardrail", model="anthropic/retired-model"),
    ]

    def fake_completion(*, model, **_kwargs):
        if model == "anthropic/retired-model":
            raise litellm.NotFoundError(
                "The model `retired-model` does not exist", model, "anthropic"
            )
        return _ok_completion()

    with patch("startup_probe.completion", side_effect=fake_completion), patch(
        "startup_probe.OpenAI", return_value=MagicMock()
    ):
        with pytest.raises(StartupProbeError) as excinfo:
            run_startup_probe(probes)

    message = str(excinfo.value)
    assert "guardrail" in message
    assert "anthropic/retired-model" in message
    assert "classifier" not in message


@pytest.mark.parametrize(
    "transient",
    [
        litellm.Timeout("timed out", "openai/gpt-4.1", "openai"),
        litellm.RateLimitError("rate limited", "openai", "openai/gpt-4.1"),
        litellm.InternalServerError("upstream 500", "openai", "openai/gpt-4.1"),
    ],
    ids=["timeout", "rate-limit", "server-error"],
)
def test_transient_provider_errors_do_not_block_startup(transient):
    """Timeouts, rate limits and 5xx on every probe return normally: the probe is for retirements, not provider weather."""
    probes = [
        ModelProbe(stage="classifier", model="openai/gpt-4.1-mini"),
        ModelProbe(stage="generator", model="openai/gpt-4.1"),
    ]
    with patch("startup_probe.completion", side_effect=transient), patch(
        "startup_probe.OpenAI", return_value=MagicMock()
    ):
        run_startup_probe(probes)  # must not raise


def test_code_fault_on_the_tool_path_fails_startup_naming_the_stage():
    """An ImportError raised only when `tools=` is passed (the #59 shape) raises StartupProbeError naming the stage, not a bare traceback."""
    probes = [
        ModelProbe(stage="classifier", model="openai/gpt-4.1-mini"),
        ModelProbe(stage="generator tool loop", model="openai/gpt-4.1", kind="chat_tools"),
    ]

    def fake_completion(*, tools=None, **_kwargs):
        if tools:
            raise ImportError("cannot import name 'CacheableResult' from 'mcp.types'")
        return _ok_completion()

    with patch("startup_probe.completion", side_effect=fake_completion), patch(
        "startup_probe.OpenAI", return_value=MagicMock()
    ):
        with pytest.raises(StartupProbeError) as excinfo:
            run_startup_probe(probes)

    message = str(excinfo.value)
    assert "generator tool loop" in message
    assert "CacheableResult" in message


def test_default_probes_exercise_the_tool_path_and_the_embedding_endpoint():
    """The default probe set makes exactly one `tools=` completion, on the generator model, and one embedding call on the configured embedding model."""
    embed_client = MagicMock()
    with patch("startup_probe.completion", side_effect=_ok_completion) as comp, patch(
        "startup_probe.OpenAI", return_value=embed_client
    ):
        run_startup_probe()

    tool_calls = [c for c in comp.call_args_list if c.kwargs.get("tools")]
    assert len(tool_calls) == 1
    assert tool_calls[0].kwargs["model"] == "openai/gpt-4.1"
    embed_client.embeddings.create.assert_called_once()
    assert embed_client.embeddings.create.call_args.kwargs["model"] == "text-embedding-3-large"


def test_every_stage_is_probed_once_under_its_current_model_name():
    """Each stage's model is called exactly once, and a swapped stage constant (as in #54) is probed under the new name, not a stale copy."""
    with patch("classifier.MODEL", "openai/swapped-classifier"), patch(
        "startup_probe.completion", side_effect=_ok_completion
    ) as comp, patch("startup_probe.OpenAI", return_value=MagicMock()) as client:
        run_startup_probe()

    models = [c.kwargs["model"] for c in comp.call_args_list]
    assert models.count("openai/swapped-classifier") == 1
    # classifier, query rewrite, rerank, generator, generator tool loop, guardrail
    assert len(models) == 6
    assert set(models) == {
        "openai/swapped-classifier",
        "openai/gpt-4.1-mini",
        "openai/gpt-4.1",
        "anthropic/claude-sonnet-4-6",
    }
    assert client.return_value.embeddings.create.call_count == 1

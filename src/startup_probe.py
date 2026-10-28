"""Startup model probe (#57): fail the Space build loudly when a configured model is gone.

Run once by `app.py` before `demo.launch()`. One minimal call per configured
model through the same LiteLLM / OpenAI SDK paths the pipeline uses. A model
the provider no longer serves (404, `NotFoundError`) raises `StartupProbeError`
so the container exits and the Space build goes red, instead of serving a chat
that fails on turn one (the five-day `gpt-4.1-nano` outage, `LIMITATIONS::O9`).

Transient provider errors (timeouts, rate limits, 5xx) do not block startup:
the probe is for retirements, not for adding a flaky dependency to cold start.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import openai
from litellm import completion
from openai import OpenAI

import classifier
import generator
import guardrail
import retrieval
import tools

PROBE_TIMEOUT_S = 30


class StartupProbeError(RuntimeError):
    """Raised when at least one configured model cannot be served."""


# Minimal tool schema so the tool-enabled probe exercises LiteLLM's tool-call
# path. The #59 outage was an ImportError raised only when `tools=` is passed;
# a plain completion to the same model succeeded (LIMITATIONS::O10).
_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "startup_probe_noop",
        "description": "Does nothing. Present so the tool-call code path runs.",
        "parameters": {"type": "object", "properties": {}},
    },
}


@dataclass(frozen=True)
class ModelProbe:
    stage: str
    model: str
    kind: Literal["chat", "chat_tools", "embedding"] = "chat"


def default_probes() -> list[ModelProbe]:
    """One probe per pipeline stage, read from the stage modules' constants so a
    model swap (#54, #55) cannot leave the probe pointing at the old name."""
    return [
        ModelProbe("classifier", classifier.MODEL),
        ModelProbe("query rewrite", retrieval.REWRITE_MODEL),
        ModelProbe("rerank", retrieval.MODEL),
        ModelProbe("generator", generator.MODEL),
        ModelProbe("generator tool loop", tools.TOOL_MODEL, kind="chat_tools"),
        ModelProbe("guardrail", guardrail.MODEL),
        ModelProbe("embeddings", retrieval.EMBED_MODEL, kind="embedding"),
    ]


def _probe_one(probe: ModelProbe) -> None:
    if probe.kind == "embedding":
        OpenAI(timeout=PROBE_TIMEOUT_S).embeddings.create(
            model=probe.model, input=["ok"]
        )
        return
    kwargs = {"tools": [_PROBE_TOOL]} if probe.kind == "chat_tools" else {}
    completion(
        model=probe.model,
        messages=[{"role": "user", "content": "ok"}],
        max_tokens=1,
        timeout=PROBE_TIMEOUT_S,
        **kwargs,
    )


def run_startup_probe(probes: list[ModelProbe] | None = None) -> None:
    if probes is None:
        probes = default_probes()
    missing: list[str] = []
    for probe in probes:
        try:
            _probe_one(probe)
        except openai.NotFoundError as e:
            missing.append(f"{probe.stage}: {probe.model} ({e})")
            continue
        except openai.APIError as e:
            # Transient provider weather (timeout, 429, 5xx, auth). The
            # pipeline's own retry policy handles these per turn; blocking
            # startup on them would make cold start flaky for no gain.
            print(
                f"[startup_probe] transient {probe.stage}: {probe.model} "
                f"({type(e).__name__}: {e})"
            )
            continue
        except Exception as e:
            # Not a provider answer at all: a code or dependency fault on this
            # call path (the #59 ImportError). It will recur on every turn, so
            # it blocks startup like a missing model does.
            missing.append(f"{probe.stage}: {probe.model} ({type(e).__name__}: {e})")
            continue
        print(f"[startup_probe] ok {probe.stage}: {probe.model}")
    if missing:
        raise StartupProbeError(
            "model probe failed; the app would fail on every turn:\n  "
            + "\n  ".join(missing)
        )


if __name__ == "__main__":
    # Standalone pre-flight: `uv run python src/startup_probe.py`
    from dotenv import load_dotenv

    load_dotenv(override=True)
    run_startup_probe()

"""Per-turn orchestrator (ADR-0003).

Wires the classify-then-route pipeline:
  classifier → branch dispatch → retrieval → composer → generator → guardrail → log

Stage latencies are measured with `time.perf_counter()`. `generation` and
`guardrail` are cumulative across retry attempts; `classifier` and `retrieval`
run once per turn (retry = re-generate-only — chunks are not re-fetched).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

import tool_loop
from branches import REGISTRY
from classifier import Classifier
from composer import PromptComposer
from generator import Generator, wrap_with_retry_feedback
from guardrail import Guardrail
from interaction_log import LogWriter
from retrieval import fetch_context, format_context
from rules import GAP_PHRASE
from tools import ToolRegistry, build_fetch_project_readme_tool

MAX_ATTEMPTS = 3
CANNED_REFUSAL = (
    "I'm sorry, I wasn't able to give you a satisfactory answer. "
    "Please reach out to Alejandro directly at alejandrofuentepinero@gmail.com."
)


class Pipeline:
    def __init__(
        self,
        classifier: Classifier,
        composer: PromptComposer,
        generator: Generator,
        guardrail: Guardrail,
        log_writer: LogWriter,
        tool_registry: ToolRegistry | None = None,
        tool_model_callable: Callable | None = None,
        registry: dict = REGISTRY,
    ):
        self._classifier = classifier
        self._composer = composer
        self._generator = generator
        self._guardrail = guardrail
        self._log_writer = log_writer
        self._tool_registry = tool_registry
        self._tool_model_callable = tool_model_callable
        self._registry = registry

    def run(
        self,
        question: str,
        history: list[dict],
        session_id: str,
        turn_index: int,
    ) -> str:
        t_total = time.perf_counter()

        # 1. Classify — filter unknown labels (e.g. TECHNICAL before #18 lands) so a
        # classifier ahead of the registry can't crash routing. Empty after filter →
        # safe fallback to GENERIC. Raw classifier output logged separately for the
        # Sentinel to surface misroute patterns.
        t = time.perf_counter()
        cls_result = self._classifier.classify(question, history)
        classifier_ms = int((time.perf_counter() - t) * 1000)
        branches = [b for b in cls_result.labels[:2] if b in self._registry] or ["GENERIC"]
        branch_name = branches[0]
        branch_spec = self._registry[branch_name]

        # 2. Retrieve (once per turn — chunks constant across retries)
        t = time.perf_counter()
        chunks = fetch_context(question, history)[: branch_spec.final_k]
        context = format_context(chunks)
        retrieval_ms = int((time.perf_counter() - t) * 1000)

        # 3. Compose system prompts (one per role, both branch-aware)
        sys_prompt_gen = self._composer.compose(branches, "generator", retrieved_context=context)
        sys_prompt_judge = self._composer.compose(branches, "guardrail", retrieved_context=context)

        # 4. Generate + evaluate, retry loop
        # For branches with tools (today: TECHNICAL), generation goes through ToolLoop
        # rather than Generator. Per Q5: each retry attempt gets its own tool budget;
        # tool_calls accumulate across attempts in the log.
        use_tools = (
            bool(branch_spec.tools)
            and self._tool_registry is not None
            and self._tool_model_callable is not None
        )
        tool_calls_log: list[dict] = []

        def _on_tool_call(name: str, args: dict, status: str) -> None:
            tool_calls_log.append({"name": name, "args": args, "status": status})

        attempts: list[dict] = []
        previous_attempt: dict | None = None
        gen_total_ms = 0
        guard_total_ms = 0
        final_answer: str | None = None
        last_answer: str | None = None

        for _ in range(MAX_ATTEMPTS):
            t = time.perf_counter()
            if use_tools:
                wrapped = wrap_with_retry_feedback(sys_prompt_gen, previous_attempt)
                messages = (
                    [{"role": "system", "content": wrapped}]
                    + history
                    + [{"role": "user", "content": question}]
                )
                tool_specs = [
                    build_fetch_project_readme_tool(self._tool_registry, on_call=_on_tool_call)
                    for tool_name in branch_spec.tools
                    if tool_name == "fetch_project_readme"
                ]
                answer = tool_loop.loop(self._tool_model_callable, messages, tool_specs)
            else:
                answer = self._generator.generate(sys_prompt_gen, history, question, previous_attempt)
            gen_total_ms += int((time.perf_counter() - t) * 1000)
            last_answer = answer

            t = time.perf_counter()
            evaluation = self._guardrail.evaluate(sys_prompt_judge, question, answer, history)
            guard_total_ms += int((time.perf_counter() - t) * 1000)

            attempts.append({
                "answer": answer,
                "is_acceptable": evaluation.is_acceptable,
                "guardrail_feedback": evaluation.feedback,
            })

            if evaluation.is_acceptable:
                final_answer = answer
                break
            previous_attempt = {"answer": answer, "feedback": evaluation.feedback}

        total_ms = int((time.perf_counter() - t_total) * 1000)

        # 5. Build + emit the enriched log record
        event_type = "answered" if final_answer is not None else "refused"
        # `knew_answer` reflects whether the KB had the info — checked against the *last* generated
        # answer (not the canned refusal), so a refused turn whose attempts contained real info
        # still scores knew_answer=True.
        knew_answer = bool(last_answer) and (GAP_PHRASE not in last_answer)

        self._log_writer.append({
            "schema_version": "1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_index": turn_index,
            "question": question,
            "event_type": event_type,
            "branch": branch_name,
            "classifier_labels": list(cls_result.labels),
            "classification_confidence": cls_result.confidence,
            "attempts": attempts,
            "retrieved_chunks": [
                {
                    "source_file": c.metadata.get("source_file", "?"),
                    "section_heading": c.metadata.get("section_heading", "?"),
                }
                for c in chunks
            ],
            "tool_calls": tool_calls_log,
            "latency_ms": {
                "classifier": classifier_ms,
                "retrieval": retrieval_ms,
                "generation": gen_total_ms,
                "guardrail": guard_total_ms,
                "total": total_ms,
            },
            "knew_answer": knew_answer,
            "contact_offered": False,
            "contact_provided": False,
        })

        return final_answer if final_answer is not None else CANNED_REFUSAL

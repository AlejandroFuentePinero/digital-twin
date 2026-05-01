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

from branches import REGISTRY
from classifier import Classifier
from composer import PromptComposer
from generator import Generator
from guardrail import Guardrail
from interaction_log import LogWriter
from retrieval import fetch_context, format_context

MAX_ATTEMPTS = 3
CANNED_REFUSAL = (
    "I'm sorry, I wasn't able to give you a satisfactory answer. "
    "Please reach out to Alejandro directly at alejandrofuentepinero@gmail.com."
)
GAP_PHRASE = "I don't have that information in my knowledge base."


class Pipeline:
    def __init__(
        self,
        classifier: Classifier,
        composer: PromptComposer,
        generator: Generator,
        guardrail: Guardrail,
        log_writer: LogWriter,
        registry: dict = REGISTRY,
    ):
        self._classifier = classifier
        self._composer = composer
        self._generator = generator
        self._guardrail = guardrail
        self._log_writer = log_writer
        self._registry = registry

    def run(
        self,
        question: str,
        history: list[dict],
        session_id: str,
        turn_index: int,
    ) -> str:
        t_total = time.perf_counter()

        # 1. Classify
        t = time.perf_counter()
        cls_result = self._classifier.classify(question, history)
        classifier_ms = int((time.perf_counter() - t) * 1000)
        # TODO(#15+): when multi-label classification lands, merge sections from labels[:2]
        branch_name = cls_result.labels[0]
        branch_spec = self._registry[branch_name]

        # 2. Retrieve (once per turn — chunks constant across retries)
        t = time.perf_counter()
        chunks = fetch_context(question, history)[: branch_spec.final_k]
        context = format_context(chunks)
        retrieval_ms = int((time.perf_counter() - t) * 1000)

        # 3. Compose system prompts (one per role, both branch-aware)
        sys_prompt_gen = self._composer.compose(branch_name, "generator", retrieved_context=context)
        sys_prompt_judge = self._composer.compose(branch_name, "guardrail", retrieved_context=context)

        # 4. Generate + evaluate, retry loop
        attempts: list[dict] = []
        previous_attempt: dict | None = None
        gen_total_ms = 0
        guard_total_ms = 0
        final_answer: str | None = None
        last_answer: str | None = None

        for _ in range(MAX_ATTEMPTS):
            t = time.perf_counter()
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
            "classification_confidence": cls_result.confidence,
            "attempts": attempts,
            "retrieved_chunks": [
                {
                    "source_file": c.metadata.get("source_file", "?"),
                    "section_heading": c.metadata.get("section_heading", "?"),
                }
                for c in chunks
            ],
            "tool_calls": [],
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

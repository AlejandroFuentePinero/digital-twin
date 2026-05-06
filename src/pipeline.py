"""Per-turn orchestrator (ADR-0003).

Wires the classify-then-route pipeline:
  classifier → branch dispatch → retrieval → composer → generator → guardrail → log

Stage latencies are measured with `time.perf_counter()`. `generation` and
`guardrail` are cumulative across retry attempts; `classifier` and `retrieval`
run once per turn (retry = re-generate-only — chunks are not re-fetched).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable

# Temporary trace instrumentation (Session 56 hang diagnosis). Set
# `PIPELINE_TRACE=1` in the env to see step-by-step progress on stderr —
# tells us exactly which call is blocking when the chat appears stuck.
# Remove once the hang is diagnosed.
_TRACE = bool(os.environ.get("PIPELINE_TRACE"))


def _trace(msg: str) -> None:
    if _TRACE:
        print(f"[pipeline-trace] {msg}", file=sys.stderr, flush=True)

import tool_loop
from branches import REGISTRY
from classifier import Classifier
from composer import PromptComposer
from event_classifier import classify_event_type
from generator import Generator, wrap_with_retry_feedback
from guardrail import Guardrail
from interaction_log import SCHEMA_VERSION, LogWriter, compute_prompt_hash
from retrieval import fetch_context, format_context
from rules import GAP_PHRASE
from tools import ToolRegistry, build_fetch_project_readme_tool

MAX_ATTEMPTS = 3
CANNED_REFUSAL = (
    "I'm sorry, I wasn't able to give you a satisfactory answer. "
    "Please reach out to Alejandro directly at alejandrofuentepinero@gmail.com."
)


def _resolve_git_sha() -> str | None:
    """Capture the current commit at module import. Returns None if git is
    unavailable or the working tree isn't a repo (e.g. installed from wheel)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


GIT_SHA: str | None = _resolve_git_sha()


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
        contact_offered: bool = False,
        contact_provided: bool = False,
    ) -> str:
        t_total = time.perf_counter()
        _trace(f"run start | session={session_id[:8]} turn={turn_index} q={question[:60]!r}")

        # 1. Classify — filter unknown labels (e.g. TECHNICAL before #18 lands) so a
        # classifier ahead of the registry can't crash routing. Empty after filter →
        # safe fallback to GENERIC. Raw classifier output logged separately for the
        # Sentinel to surface misroute patterns.
        _trace("classify start")
        t = time.perf_counter()
        cls_result = self._classifier.classify(question, history)
        classifier_ms = int((time.perf_counter() - t) * 1000)
        _trace(f"classify done | {classifier_ms}ms | labels={cls_result.labels} confidence={cls_result.confidence:.2f}")
        branches = [b for b in cls_result.labels[:2] if b in self._registry] or ["GENERIC"]
        branch_name = branches[0]
        branch_spec = self._registry[branch_name]

        # 2. Retrieve (once per turn — chunks constant across retries)
        _trace(f"retrieve start | branch={branch_name}")
        t = time.perf_counter()
        chunks = fetch_context(question, history)[: branch_spec.final_k]
        context = format_context(chunks)
        retrieval_ms = int((time.perf_counter() - t) * 1000)
        _trace(f"retrieve done | {retrieval_ms}ms | {len(chunks)} chunks")

        # 3. Compose system prompts (one per role, both branch-aware)
        sys_prompt_gen = self._composer.compose(branches, "generator", retrieved_context=context)
        sys_prompt_judge = self._composer.compose(branches, "guardrail", retrieved_context=context)

        # Fingerprint the first-attempt prompt — retries reuse the same
        # structural prompt with feedback appended, so hashing once captures
        # the "this was the question + rules + chunks" identity (issue #37).
        prompt_hash = compute_prompt_hash(sys_prompt_gen, question)

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
        # Per-turn accumulation of tool-fetched content so the guardrail can see
        # what the model actually grounded in. Without this, tool-grounded answers
        # are rejected as "fabrication" because the guardrail's retrieved_context
        # only carries KB chunks. See LIMITATIONS bug surfaced in #18 smoke-test
        # Q8.2 — the digital_twin self-reference case where KB has no overlap with
        # the tool-returned README.
        tool_content_for_judge: list[tuple[str, dict, str]] = []
        # Mutable index so the callback closure can stamp each tool call with the
        # attempt that triggered it — lets per-attempt debugging trace which retry
        # invoked which tool, separately from the per-attempt accumulation in attempts[].
        current_attempt_index = [0]

        def _on_tool_call(name: str, args: dict, status: str, content: str | None) -> None:
            tool_calls_log.append({
                "name": name,
                "args": args,
                "status": status,
                "attempt_index": current_attempt_index[0],
            })
            if status == "success" and content is not None:
                tool_content_for_judge.append((name, args, content))

        attempts: list[dict] = []
        previous_attempt: dict | None = None
        gen_total_ms = 0
        guard_total_ms = 0
        final_answer: str | None = None
        last_answer: str | None = None

        for attempt_idx in range(MAX_ATTEMPTS):
            current_attempt_index[0] = attempt_idx
            answer: str | None = None
            evaluation = None
            attempt_exception: str | None = None

            # Generation step — exceptions here (tenacity exhaustion, oversized
            # prompt, provider 4xx etc.) are treated as a failed attempt rather
            # than allowed to bubble out. Without this, MAX_ATTEMPTS / CANNED_REFUSAL
            # never fires; the exception jumps over the for-loop and skips the
            # graceful-fallback return at the bottom.
            _trace(f"attempt {attempt_idx + 1}/{MAX_ATTEMPTS} | generate start (use_tools={use_tools})")
            t = time.perf_counter()
            try:
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
                last_answer = answer
                _trace(f"attempt {attempt_idx + 1} | generate done | {len(answer or '')} chars")
            except Exception as e:
                attempt_exception = f"{type(e).__name__}: {e}"
                _trace(f"attempt {attempt_idx + 1} | generate raised | {attempt_exception}")
            gen_total_ms += int((time.perf_counter() - t) * 1000)

            # Guardrail step — skip if generation already failed; otherwise
            # exceptions here are also treated as a failed attempt.
            if attempt_exception is None:
                if tool_content_for_judge:
                    tool_block = "\n\n## Tool-fetched content available to the model\n\n" + "\n\n---\n\n".join(
                        f"[{name}({args})]\n{content}"
                        for name, args, content in tool_content_for_judge
                    )
                    judge_context = context + tool_block
                    sys_prompt_judge_for_attempt = self._composer.compose(
                        branches, "guardrail", retrieved_context=judge_context
                    )
                else:
                    sys_prompt_judge_for_attempt = sys_prompt_judge

                _trace(f"attempt {attempt_idx + 1} | guardrail start")
                t = time.perf_counter()
                try:
                    evaluation = self._guardrail.evaluate(sys_prompt_judge_for_attempt, question, answer, history)
                    _trace(f"attempt {attempt_idx + 1} | guardrail done | acceptable={evaluation.is_acceptable}")
                except Exception as e:
                    attempt_exception = f"{type(e).__name__}: {e}"
                    _trace(f"attempt {attempt_idx + 1} | guardrail raised | {attempt_exception}")
                guard_total_ms += int((time.perf_counter() - t) * 1000)

            if attempt_exception is not None:
                attempts.append({
                    "answer": answer,
                    "is_acceptable": False,
                    "guardrail_feedback": f"pipeline call raised: {attempt_exception}",
                })
                previous_attempt = {
                    "answer": answer or "(no answer — exception during generation)",
                    "feedback": f"previous attempt failed with: {attempt_exception}",
                }
                continue

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
        event_type = classify_event_type(branch_name, final_answer)
        # `knew_answer` populated for v3-record consumer compat. Consumer
        # migration is complete (PRD #41 slice 3 — no consumer in src/ reads
        # this field; failure_feed / cluster_gaps / summarize_failures /
        # flag_detector / dashboard_model all read `event_type` directly).
        # TODO(v5): drop this write in the next schema bump.
        knew_answer = bool(last_answer) and (GAP_PHRASE not in last_answer)

        self._log_writer.append({
            "schema_version": SCHEMA_VERSION,
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
            "contact_offered": contact_offered,
            "contact_provided": contact_provided,
            "git_sha": GIT_SHA,
            "model_id": getattr(self._generator, "MODEL", None),
            "temperature": getattr(self._generator, "TEMPERATURE", None),
            "prompt_hash": prompt_hash,
        })

        result = final_answer if final_answer is not None else CANNED_REFUSAL
        _trace(f"run done | {int((time.perf_counter() - t_total) * 1000)}ms total | event={event_type} | return_len={len(result)}")
        return result

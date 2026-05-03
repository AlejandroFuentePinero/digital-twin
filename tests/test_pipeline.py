import json
from unittest.mock import patch

import pytest

from branches import REGISTRY
from classifier import ClassifierResult
from composer import PromptComposer
from guardrail import Evaluation
from interaction_log import LogReader, LogWriter
from pipeline import CANNED_REFUSAL, MAX_ATTEMPTS, Pipeline
from profile import ProfileLoader
from retrieval import Chunk
from tool_loop import ModelResponse, ToolCall
from tools import ToolRegistry


# ---------------------------------------------------------------------------
# Fakes — boundary deps. We control inputs and observe what the pipeline does.
# ---------------------------------------------------------------------------


class FakeClassifier:
    def __init__(self, result: ClassifierResult):
        self.result = result
        self.calls = 0

    def classify(self, question, history):
        self.calls += 1
        return self.result


class FakeGenerator:
    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def generate(self, system_prompt, history, question, previous_attempt=None):
        self.calls.append({
            "system_prompt": system_prompt,
            "question": question,
            "previous_attempt": previous_attempt,
        })
        return self.answers.pop(0)


class FakeGuardrail:
    def __init__(self, evaluations: list[Evaluation]):
        self.evaluations = list(evaluations)
        self.calls: list[dict] = []

    def evaluate(self, system_prompt, question, answer, history):
        self.calls.append({"system_prompt": system_prompt, "question": question, "answer": answer})
        return self.evaluations.pop(0)


class FakeToolModelCallable:
    """Returns scripted ModelResponses; records every call. Used for the TECHNICAL/ToolLoop path."""

    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if not self.responses:
            raise RuntimeError("FakeToolModelCallable: no scripted responses left")
        return self.responses.pop(0)


@pytest.fixture
def fake_tool_registry(tmp_path):
    """Tiny fixture registry with two project READMEs."""
    (tmp_path / "ai_jie.md").write_text(
        "# AI-JIE\n\n**Source:** https://github.com/example/ai-jie\n\nAI-JIE README BODY."
    )
    (tmp_path / "expert_knowledge_worker.md").write_text(
        "# Expert Knowledge Worker\n\n**Source:** https://github.com/example/ekw\n\nEKW README BODY."
    )
    registry = {
        "ai_jie": {
            "path": "ai_jie.md",
            "title": "AI-JIE",
            "summary": "Structured extraction pipeline.",
            "kb_cross_reference": "projects_ai_flagship.md",
            "link": "https://github.com/example/ai-jie",
        },
        "expert_knowledge_worker": {
            "path": "expert_knowledge_worker.md",
            "title": "Expert Knowledge Worker",
            "summary": "RAG chatbot.",
            "kb_cross_reference": "projects_ai_flagship.md",
            "link": "https://github.com/example/ekw",
        },
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    return ToolRegistry(registry_path)


@pytest.fixture
def real_composer(tmp_path):
    """A real PromptComposer wired to a minimal profile fixture covering every section any registered branch loads."""
    p = tmp_path / "profile.md"
    p.write_text(
        "## identity\nIDENTITY body.\n\n"
        "## narrative_summary\nNARRATIVE body.\n\n"
        "## transfer_principles\nTRANSFER body.\n\n"
        "## gap_inventory\nGAP-INVENTORY body.\n\n"
        "## active_learning\nACTIVE-LEARNING body.\n\n"
        "## logistics\nLOGISTICS body — Melbourne, hybrid, contact directly.\n\n"
        "## personal_stories\nPERSONAL-STORIES body — seven STAR anecdotes plus routing guide.\n"
    )
    return PromptComposer(ProfileLoader(p), REGISTRY)


@pytest.fixture
def fake_chunks():
    return [
        Chunk(page_content="chunk1 body", metadata={"source_file": "identity.md", "section_heading": "identity"}),
        Chunk(page_content="chunk2 body", metadata={"source_file": "experience.md", "section_heading": "Bolivia"}),
    ]


def _build_pipeline(
    real_composer,
    classifier,
    generator,
    guardrail,
    log_path,
    tool_registry=None,
    tool_model_callable=None,
):
    return Pipeline(
        classifier=classifier,
        composer=real_composer,
        generator=generator,
        guardrail=guardrail,
        log_writer=LogWriter(log_path),
        tool_registry=tool_registry,
        tool_model_callable=tool_model_callable,
    )


def test_happy_path_returns_generator_answer_and_logs_event_answered(real_composer, fake_chunks, tmp_path):
    """Guardrail accepts on first attempt → returns the generator's answer; log carries event_type='answered' and one attempt."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["GENERIC"], confidence=1.0))
    generator = FakeGenerator(answers=["happy answer"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        out = pipeline.run("What is your background?", history=[], session_id="s1", turn_index=0)

    assert out == "happy answer"
    record = LogReader(log_path).read_all()[0]
    assert record["event_type"] == "answered"
    assert len(record["attempts"]) == 1
    assert record["attempts"][0]["is_acceptable"] is True


def test_retry_loop_returns_second_answer_when_first_is_rejected(real_composer, fake_chunks, tmp_path):
    """Guardrail rejects attempt 1 and accepts attempt 2 — pipeline returns the second answer; second generate call sees previous_attempt."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["GENERIC"], confidence=1.0))
    generator = FakeGenerator(answers=["first answer", "second answer"])
    guardrail = FakeGuardrail(evaluations=[
        Evaluation(is_acceptable=False, feedback="not specific enough"),
        Evaluation(is_acceptable=True, feedback="ok"),
    ])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        out = pipeline.run("q", history=[], session_id="s1", turn_index=0)

    assert out == "second answer"
    # Second generator call received the rejected first answer + feedback
    assert generator.calls[1]["previous_attempt"] == {
        "answer": "first answer",
        "feedback": "not specific enough",
    }
    record = LogReader(log_path).read_all()[0]
    assert record["event_type"] == "answered"
    assert len(record["attempts"]) == 2
    assert [a["answer"] for a in record["attempts"]] == ["first answer", "second answer"]


def test_canned_refusal_when_all_attempts_rejected(real_composer, fake_chunks, tmp_path):
    """Guardrail rejects all MAX_ATTEMPTS — pipeline returns CANNED_REFUSAL; log marks event_type='refused'; knew_answer reflects whether the last generated answer was a real answer (not gap phrase)."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["GENERIC"], confidence=1.0))
    generator = FakeGenerator(answers=[f"answer {i}" for i in range(MAX_ATTEMPTS)])
    guardrail = FakeGuardrail(evaluations=[
        Evaluation(is_acceptable=False, feedback="bad") for _ in range(MAX_ATTEMPTS)
    ])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        out = pipeline.run("q", history=[], session_id="s1", turn_index=0)

    assert out == CANNED_REFUSAL
    record = LogReader(log_path).read_all()[0]
    assert record["event_type"] == "refused"
    assert len(record["attempts"]) == MAX_ATTEMPTS
    # The last generated answer was "answer 2" — not the gap phrase, so knew_answer=True even on a refused turn
    assert record["knew_answer"] is True


def test_retrieval_called_once_per_turn_even_with_retries(real_composer, fake_chunks, tmp_path):
    """fetch_context runs exactly once per turn — retries re-generate but chunks stay constant (per ADR-0003 / issue #13 spec)."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["GENERIC"], confidence=1.0))
    generator = FakeGenerator(answers=[f"a{i}" for i in range(MAX_ATTEMPTS)])
    guardrail = FakeGuardrail(evaluations=[
        Evaluation(is_acceptable=False, feedback="x") for _ in range(MAX_ATTEMPTS)
    ])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks) as mock_fetch:
        pipeline.run("q", history=[], session_id="s1", turn_index=0)

    assert mock_fetch.call_count == 1, "fetch_context must run once per turn, not per attempt"
    assert classifier.calls == 1, "classifier must run once per turn"
    assert len(generator.calls) == MAX_ATTEMPTS
    assert len(guardrail.calls) == MAX_ATTEMPTS


def test_gap_classification_routes_to_gap_branch_with_calibration_ladder_and_gap_inventory(real_composer, fake_chunks, tmp_path):
    """End-to-end: classifier predicts GAP → generator's system prompt carries the calibration_ladder rule and the gap_inventory section."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["GAP"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("Do you have AWS experience?", history=[], session_id="s1", turn_index=0)

    sys_prompt = generator.calls[0]["system_prompt"]
    assert "Calibration ladder" in sys_prompt, "GAP branch_rule (calibration_ladder) must reach the generator"
    assert "GAP-INVENTORY" in sys_prompt, "GAP profile section (gap_inventory marker) must reach the generator"
    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "GAP"
    assert record["classifier_labels"] == ["GAP"]


def test_pipeline_falls_back_to_generic_when_classifier_predicts_unknown_branch(real_composer, fake_chunks, tmp_path):
    """Classifier predicts a label not in REGISTRY (e.g. a future branch) — pipeline falls back to GENERIC for safety."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["UNKNOWN_FUTURE_BRANCH"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("q", history=[], session_id="s1", turn_index=0)

    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "GENERIC", "unknown predicted label must fall back to the safe broad branch"


def test_pipeline_filters_unknown_labels_and_keeps_known_ones(real_composer, fake_chunks, tmp_path):
    """Multi-label classifier output mixing known + unknown branches — unknown filtered, known kept; primary is the first surviving label."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["UNKNOWN_FUTURE_BRANCH", "GAP"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("q", history=[], session_id="s1", turn_index=0)

    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "GAP", "UNKNOWN_FUTURE_BRANCH filtered (not in REGISTRY); GAP becomes primary"


def test_pipeline_logs_raw_classifier_labels_distinct_from_used_branch(real_composer, fake_chunks, tmp_path):
    """The log carries `classifier_labels` (raw) alongside `branch` (used) so misroute patterns stay observable for the Sentinel."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["UNKNOWN_FUTURE_BRANCH", "GAP"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("q", history=[], session_id="s1", turn_index=0)

    record = LogReader(log_path).read_all()[0]
    assert record["classifier_labels"] == ["UNKNOWN_FUTURE_BRANCH", "GAP"], "raw classifier output preserved for observability"
    assert record["branch"] == "GAP", "unknown label filtered, GAP becomes primary"


def test_logistical_classification_routes_to_logistical_branch_with_logistics_section(real_composer, fake_chunks, tmp_path):
    """End-to-end: classifier predicts LOGISTICAL → generator's system prompt carries the logistics section.

    Per #19. R2 smoke-test (Q8.3) showed the classifier predicting [LOGISTICAL] at 0.95
    confidence today; before this slice the pipeline filter-fell-back to GENERIC because
    LOGISTICAL was not in REGISTRY. This test locks the routing path: when LOGISTICAL is
    in the registry, the same classification reaches its own branch prompt.
    """
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["LOGISTICAL"], confidence=0.95))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("What's your notice period?", history=[], session_id="s1", turn_index=0)

    sys_prompt = generator.calls[0]["system_prompt"]
    assert "LOGISTICS body" in sys_prompt, "LOGISTICAL profile section (logistics) must reach the generator"
    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "LOGISTICAL"
    assert record["classifier_labels"] == ["LOGISTICAL"]


def test_behavioural_classification_routes_to_behavioural_branch_with_personal_stories_section(real_composer, fake_chunks, tmp_path):
    """End-to-end: classifier predicts BEHAVIOURAL → generator's system prompt carries the deflection rule + personal_stories section.

    Per #17. Behavioural probes ("tell me about a time you failed", "describe a
    conflict") were filter-falling-back to GENERIC before this slice because
    BEHAVIOURAL was not in REGISTRY. This test locks the routing path: when
    BEHAVIOURAL is registered, the same classification reaches its own branch
    prompt with both the personal_stories section content and the deflection-rule
    guidance available to the generator.
    """
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["BEHAVIOURAL"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("Tell me about a time you failed.", history=[], session_id="s1", turn_index=0)

    sys_prompt = generator.calls[0]["system_prompt"]
    assert "PERSONAL-STORIES body" in sys_prompt, "BEHAVIOURAL profile section (personal_stories) must reach the generator"
    assert "personal_stories" in sys_prompt, "deflection rule must name the section by key"
    assert "fabricat" in sys_prompt.lower(), "deflection rule must forbid fabrication in the generator's view"
    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "BEHAVIOURAL"
    assert record["classifier_labels"] == ["BEHAVIOURAL"]


def test_technical_classification_routes_to_technical_branch_with_transfer_principles(real_composer, fake_chunks, fake_tool_registry, tmp_path):
    """End-to-end: classifier predicts TECHNICAL → ToolLoop path → transfer_principles + tool_rules reach the system prompt.

    Per #18. The model returns text directly (no tool call) for this happy-path case;
    the tool-execution paths are exercised in subsequent tests.
    """
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["TECHNICAL"], confidence=0.9))
    generator = FakeGenerator(answers=["unused — TECHNICAL uses ToolLoop"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])
    tool_model = FakeToolModelCallable([
        ModelResponse(content="answer about Expert Knowledge Worker", tool_calls=[]),
    ])

    pipeline = _build_pipeline(
        real_composer, classifier, generator, guardrail, log_path,
        tool_registry=fake_tool_registry, tool_model_callable=tool_model,
    )
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        out = pipeline.run("How does EKW work?", history=[], session_id="s1", turn_index=0)

    assert out == "answer about Expert Knowledge Worker"
    # Generator NOT called — ToolLoop path took over for TECHNICAL branch
    assert generator.calls == [], "TECHNICAL branch must use ToolLoop, not Generator"
    # ToolLoop's system prompt carries TECHNICAL's signals
    sys_msg = tool_model.calls[0]["messages"][0]
    assert sys_msg["role"] == "system"
    assert "TRANSFER body" in sys_msg["content"], "transfer_principles must reach the tool-loop system prompt"
    assert "fetch_project_readme" in sys_msg["content"], "tool_rules names the tool — must reach the prompt"
    # Tool schemas passed to model_callable include the project enum
    schemas = tool_model.calls[0]["tools"]
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "fetch_project_readme"
    enum = schemas[0]["function"]["parameters"]["properties"]["project"]["enum"]
    assert "ai_jie" in enum and "expert_knowledge_worker" in enum
    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "TECHNICAL"
    assert record["tool_calls"] == [], "no tool call invoked on this happy-path turn"


def test_technical_branch_records_tool_calls_in_log_when_model_invokes_tool(real_composer, fake_chunks, fake_tool_registry, tmp_path):
    """Model issues a tool_call → handler fetches the README → tool_calls log captures {name, args, status}."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["TECHNICAL"], confidence=0.9))
    generator = FakeGenerator(answers=[])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])
    tool_model = FakeToolModelCallable([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="fetch_project_readme", arguments={"project": "ai_jie"})],
        ),
        ModelResponse(content="grounded answer about AI-JIE", tool_calls=[]),
    ])

    pipeline = _build_pipeline(
        real_composer, classifier, generator, guardrail, log_path,
        tool_registry=fake_tool_registry, tool_model_callable=tool_model,
    )
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        out = pipeline.run("Tell me about AI-JIE's chain-of-thought scaffolding.", history=[], session_id="s1", turn_index=0)

    assert out == "grounded answer about AI-JIE"
    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "TECHNICAL"
    assert record["tool_calls"] == [
        {"name": "fetch_project_readme", "args": {"project": "ai_jie"}, "status": "success", "attempt_index": 0}
    ]
    # The tool result reached the second model call
    second_messages = tool_model.calls[1]["messages"]
    tool_result_msgs = [m for m in second_messages if m.get("role") == "tool"]
    assert tool_result_msgs and "AI-JIE README BODY" in tool_result_msgs[0]["content"]


def test_technical_branch_per_attempt_tool_budget_resets_on_retry(real_composer, fake_chunks, fake_tool_registry, tmp_path):
    """Per Q5: each retry attempt gets its own ToolLoop budget. Tool calls accumulate across attempts in the log."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["TECHNICAL"], confidence=0.9))
    generator = FakeGenerator(answers=[])
    guardrail = FakeGuardrail(evaluations=[
        Evaluation(is_acceptable=False, feedback="not specific enough"),
        Evaluation(is_acceptable=True, feedback="ok"),
    ])
    # Attempt 1: model calls tool, then text. Attempt 2: model calls tool, then text.
    tool_model = FakeToolModelCallable([
        ModelResponse(content=None, tool_calls=[ToolCall(id="c1", name="fetch_project_readme", arguments={"project": "ai_jie"})]),
        ModelResponse(content="first attempt answer", tool_calls=[]),
        ModelResponse(content=None, tool_calls=[ToolCall(id="c2", name="fetch_project_readme", arguments={"project": "expert_knowledge_worker"})]),
        ModelResponse(content="second attempt answer", tool_calls=[]),
    ])

    pipeline = _build_pipeline(
        real_composer, classifier, generator, guardrail, log_path,
        tool_registry=fake_tool_registry, tool_model_callable=tool_model,
    )
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        out = pipeline.run("Q", history=[], session_id="s1", turn_index=0)

    assert out == "second attempt answer"
    record = LogReader(log_path).read_all()[0]
    # Both attempts' tool calls accumulate in log; attempt_index attributes each call to its retry
    assert record["tool_calls"] == [
        {"name": "fetch_project_readme", "args": {"project": "ai_jie"}, "status": "success", "attempt_index": 0},
        {"name": "fetch_project_readme", "args": {"project": "expert_knowledge_worker"}, "status": "success", "attempt_index": 1},
    ]
    # Two attempts in attempts[]
    assert len(record["attempts"]) == 2


def test_log_record_carries_full_schema_with_branch_classification_chunks_and_latencies(real_composer, fake_chunks, tmp_path):
    """Every required schema field appears in the log record and carries plausible values."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["GENERIC"], confidence=0.87))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("the question", history=[], session_id="sess-xyz", turn_index=4)

    record = LogReader(log_path).read_all()[0]
    # Identity / addressing fields
    assert record["schema_version"] == "1"
    assert record["session_id"] == "sess-xyz"
    assert record["turn_index"] == 4
    assert record["question"] == "the question"
    assert "T" in record["timestamp"]  # ISO-8601 stamp
    # Routing fields
    assert record["branch"] == "GENERIC"
    assert record["classifier_labels"] == ["GENERIC"]
    assert record["classification_confidence"] == 0.87
    # Retrieved chunks logged as references, not full content
    assert record["retrieved_chunks"] == [
        {"source_file": "identity.md", "section_heading": "identity"},
        {"source_file": "experience.md", "section_heading": "Bolivia"},
    ]
    # Tool calls + contact flags default-empty
    assert record["tool_calls"] == []
    assert record["contact_offered"] is False
    assert record["contact_provided"] is False
    # Latency block carries all five keys
    assert set(record["latency_ms"].keys()) == {"classifier", "retrieval", "generation", "guardrail", "total"}
    for k, v in record["latency_ms"].items():
        assert isinstance(v, int) and v >= 0, f"latency_ms[{k}] should be a non-negative int"

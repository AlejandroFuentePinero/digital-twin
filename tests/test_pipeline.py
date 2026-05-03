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
        "## logistics\nLOGISTICS body — Melbourne, hybrid, contact directly.\n"
    )
    return PromptComposer(ProfileLoader(p), REGISTRY)


@pytest.fixture
def fake_chunks():
    return [
        Chunk(page_content="chunk1 body", metadata={"source_file": "identity.md", "section_heading": "identity"}),
        Chunk(page_content="chunk2 body", metadata={"source_file": "experience.md", "section_heading": "Bolivia"}),
    ]


def _build_pipeline(real_composer, classifier, generator, guardrail, log_path):
    return Pipeline(
        classifier=classifier,
        composer=real_composer,
        generator=generator,
        guardrail=guardrail,
        log_writer=LogWriter(log_path),
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
    """Classifier predicts a label not yet in REGISTRY (e.g. TECHNICAL before #18 lands) — pipeline falls back to GENERIC for safety."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["TECHNICAL"], confidence=0.9))
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
    classifier = FakeClassifier(ClassifierResult(labels=["TECHNICAL", "GAP"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("q", history=[], session_id="s1", turn_index=0)

    record = LogReader(log_path).read_all()[0]
    assert record["branch"] == "GAP", "TECHNICAL filtered (unknown today); GAP becomes primary"


def test_pipeline_logs_raw_classifier_labels_distinct_from_used_branch(real_composer, fake_chunks, tmp_path):
    """The log carries `classifier_labels` (raw) alongside `branch` (used) so misroute patterns stay observable for the Sentinel."""
    log_path = tmp_path / "interactions.jsonl"
    classifier = FakeClassifier(ClassifierResult(labels=["TECHNICAL", "GAP"], confidence=0.9))
    generator = FakeGenerator(answers=["A"])
    guardrail = FakeGuardrail(evaluations=[Evaluation(is_acceptable=True, feedback="ok")])

    pipeline = _build_pipeline(real_composer, classifier, generator, guardrail, log_path)
    with patch("pipeline.fetch_context", return_value=fake_chunks):
        pipeline.run("q", history=[], session_id="s1", turn_index=0)

    record = LogReader(log_path).read_all()[0]
    assert record["classifier_labels"] == ["TECHNICAL", "GAP"], "raw classifier output preserved for observability"
    assert record["branch"] == "GAP"


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

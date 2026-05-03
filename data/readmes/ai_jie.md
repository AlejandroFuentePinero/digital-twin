# AI-JIE — Automated Job Information Extraction

**Source:** https://github.com/AlejandroFuentePinero/ai-jie
**Technical report:** https://github.com/AlejandroFuentePinero/ai-jie/blob/main/docs/technical_report.md
**Dataset (preprocessed):** https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-preprocessed

## What it is

A structured extraction pipeline that turns raw job-posting text into validated, intent-classified `Job` objects at scale. Built as the **extraction layer for the Job Intelligence Engine** — feeds the downstream market-modelling and recommendation system. Status: complete; 3,892 Data Scientist postings extracted at prompt v33; dataset published to HuggingFace Hub in two versions (preprocessed with chain-of-thought intact, and postprocessed with deterministic cleanup applied).

The single hardest problem the project solves: **getting the LLM to reliably distinguish required vs preferred vs soft skills**, and to **separate genuine skill demands from responsibilities described as skills**. Solved through 33 prompt iterations and an architectural shift to chain-of-thought scaffolding.

## Architecture

Three-layer pipeline:

### 1. Schema-driven LLM extraction (`src/data_ingestion/parser.py`, `models.py`)

Each posting is parsed into a `Job` Pydantic object with:

- **Skills partitioned by intent** — `skills_required`, `skills_preferred`, `skills_soft`
- **Role metadata** — seniority, job family, years of experience, education, key responsibilities
- **Company metadata** — name, description
- **Chain-of-thought scaffolding fields** — `responsibility_skills_found`, `preferred_signals_found`, `all_technical_skills` — intermediate reasoning fields that force an extract-then-classify architecture and feed the postprocessing layer downstream

The `instructor` library enforces Pydantic schema validation on every LLM response — malformed extractions become retries rather than silent corruption.

### 2. Deterministic postprocessing (`src/data_ingestion/postprocess.py`)

Rule-based cleanup applied AFTER LLM extraction:

- **Responsibility exclusion** — strips skills that the chain-of-thought identified as responsibilities mislabelled as requirements
- **Blocklist filtering** — removes a curated set of false-positive tokens that the LLM consistently extracts but that aren't real skills

The LLM extracts broadly and inclusively; the deterministic layer handles known noise patterns reproducibly. This split keeps the LLM prompt simple and the noise-handling auditable.

### 3. Batch orchestration (`src/data_ingestion/pipeline.py`)

- **Async concurrency** via `asyncio` for high throughput.
- **Fault-tolerant JSONL checkpointing** — pipeline resumes from the last successful row if interrupted; idempotent (re-running on a complete output is a no-op); tolerates corrupt lines without crashing.

## Key engineering decisions

- **Chain-of-thought scaffolding was the single largest accuracy gain across all 33 prompt versions.** Early prompts asked the model to directly classify skills into required/preferred/soft. Accuracy on preferred was poor — the model conflated responsibilities with requirements. The fix: add intermediate Pydantic fields (`responsibility_skills_found`, `preferred_signals_found`, `all_technical_skills`) that **force explicit reasoning before classification**. Architectural change, not a wording tweak.
- **`instructor` library as a structural constraint**, not as ergonomic sugar. Schema validation on every LLM response prevents downstream code from ever seeing malformed extractions.
- **Two-model cost separation.** `gpt-5.4-mini` for high-volume extraction; a separate LLM as independent judge for evaluation. Different cost profile per role and prevents self-evaluation bias (the same model judging its own output is unreliable).
- **Postprocessing is deterministic, not LLM-based.** The known-noise pattern (responsibilities-as-skills, generic tokens) is best handled by rules — reproducible across runs, auditable, fast. The LLM does the hard pattern recognition; rules clean up the consistent leftovers.
- **Resumable pipeline with checkpointing.** 3,892 postings × LLM call latency = many hours. Checkpoint persistence makes the pipeline survivable across notebook restarts and network drops.

## Evaluation

Two-tier evaluation framework:

### Tier 1 — LLM-as-judge across prompt iterations

- **Scale:** 1–3 per dimension, fixed sample of 50 postings (seed=42 for reproducibility).
- **Tracked across all 33 prompt versions** — the prompt-engineering retrospective lives in the technical report.
- **Architectural baseline (v9g):** overall **2.98 / 3.00** — the chain-of-thought architectural change is the moment scores plateaued near ceiling.

### Tier 2 — Human evaluation

28 postings scored 1–5 across 9 dimensions by an independent human rater. Cohen's kappa computed across dimensions for inter-rater calibration of the LLM judge.

| Dimension | Human / 5 |
|---|---|
| Seniority | 5.00 |
| Responsibilities | 5.00 |
| Null appropriateness | 5.00 |
| Skills soft | 4.93 |
| Years experience | 4.93 |
| Education | 4.93 |
| Job family | 4.79 |
| Skills preferred | 4.50 |
| **Skills required** | **4.00** |
| **Overall** | **4.11** |

Structural fields are near-perfect; the residual noise in `skills_required` is exactly what the postprocessing layer handles.

## Production engineering

- **GitHub Actions CI** — pytest runs on every push.
- **Unit tests** — postprocessing idempotency (`apply_responsibility_exclusion`, `_remove_blocked`, `postprocess()` consistency); pipeline checkpoint/resume logic (idempotency, no duplicates, corrupt-line tolerance).
- **`pyproject.toml` with pinned dependencies**, Python 3.13+.

## Stack

Python 3.13 · OpenAI API (`gpt-5.4-mini`) · `instructor` · Pydantic · `asyncio` · HuggingFace Hub · pytest · GitHub Actions

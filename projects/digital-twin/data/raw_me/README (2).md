# AI-JIE — Automated Job Information Extraction

A structured extraction pipeline that turns raw job posting text into validated, intent-classified `Job` objects at scale. Built as the extraction layer for the [Job Intelligence Engine](https://github.com/AlejandroFuentePinero/job-intelligence-engine).

**Status**: Complete — 3,892 DS job postings extracted at prompt v33, dataset published to HuggingFace Hub. The pipeline supports both Data Scientist and Data Analyst CSVs; only the DS dataset has been run through the full batch to date.

---

## What It Produces

Each posting is parsed into a `Job` object containing:

- **Skills partitioned by intent** — `skills_required`, `skills_preferred`, `skills_soft`
- **Role metadata** — seniority, job family, years of experience, education, key responsibilities
- **Company metadata** — name, description
- **Chain-of-thought scaffolding** — intermediate reasoning fields (`responsibility_skills_found`, `preferred_signals_found`, `all_technical_skills`) that enforce an extract-then-classify architecture and feed the deterministic postprocessing layer

Full schema: `src/data_ingestion/models.py`

**Stack**: Python · OpenAI (`gpt-5.4-mini`) · `instructor` · `asyncio` · Pydantic · HuggingFace Hub

---

## Results

Human evaluation of 28 postings (scale 1–5). Structural fields are near-perfect; the main noise in `skills_required` is handled by the postprocessing layer.

| Dimension | Score / 5 |
|-----------|-----------|
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

Prompt development was tracked via an LLM-as-a-Judge framework across 33 versions (1–3 scale, n=50 fixed sample). Architectural baseline v9g: overall **2.98/3.00**. See [`docs/technical_report.md`](docs/technical_report.md) for the full evaluation methodology, version history, and human eval detail.

---

## Dataset

| Repo | Content |
|------|---------|
| [`Alejandrofupi/ai-jie-jobs-lite-preprocessed`](https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-preprocessed) | 3,892 DS postings — raw LLM output, scaffolding intact |
| [`Alejandrofupi/ai-jie-jobs-lite-postprocessed`](https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-postprocessed) | 3,892 DS postings — responsibility exclusion applied, blocklist filtered, scaffolding stripped |

Source CSVs originate from the [Glassdoor Job Listings dataset on Kaggle](https://www.kaggle.com/datasets/rashikrahmanpritom/data-science-job-posting-on-glassdoor). They are not committed to this repo — download them manually and place them at `data/raw/DataScientist.csv` and `data/raw/DataAnalyst.csv` before running the pipeline.

---

## Quick Start

**Prerequisites**: Python 3.13+, OpenAI API key, HuggingFace token.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # installs all deps + pytest from pyproject.toml
cp .env.example .env           # add OPENAI_API_KEY and HF_TOKEN
```

Download `DataScientist.csv` (and optionally `DataAnalyst.csv`) from the [Kaggle dataset](https://www.kaggle.com/datasets/rashikrahmanpritom/data-science-job-posting-on-glassdoor) and place them under `data/raw/`. The directory is gitignored; the files are not distributed with this repo.

### Extraction pipeline

```bash
# DS jobs only → data/processed/jobs_lite.jsonl (resumes from checkpoint if interrupted)
# This is the mode used for the published dataset
python -m src.data_ingestion.pipeline

# DS + DA jobs → data/processed/jobs_full.jsonl
# Run this to extend the dataset to include Data Analyst postings
python -m src.data_ingestion.pipeline --full

# Extract + push preprocessed and postprocessed repos to HuggingFace Hub
python -m src.data_ingestion.pipeline --push
python -m src.data_ingestion.pipeline --full --push

# Re-apply postprocessing and re-push without re-extracting
python -m src.data_ingestion.pipeline --postprocess --push
```

### Evaluation

```python
import asyncio
from dotenv import load_dotenv; load_dotenv()
from src.data_ingestion.loader import load_raw_jobs
from src.evals.runner import run_eval
from src.config import EVALS_RESULTS_DIR

df = load_raw_jobs(da_path=False)
asyncio.run(run_eval(df, output_root=EVALS_RESULTS_DIR, n=50, seed=42, prompt_version="v33"))
```

```bash
# Regenerate trajectory plots across all eval runs
python -m src.evals.eval_trend
```

### Tests

```bash
python -m pytest tests/ -v
```

Tests run automatically on every push via GitHub Actions (`.github/workflows/ci.yml`).

Unit tests cover:
- Deterministic postprocessing (`apply_responsibility_exclusion`, `_remove_blocked`, `postprocess()` / `postprocess_df()` consistency)
- Pipeline checkpoint/resume logic (idempotency, no duplicates, corrupt-line tolerance)

---

## Project Structure

```
ai-jie/
├── src/
│   ├── config.py
│   ├── data_ingestion/
│   │   ├── models.py          # Pydantic schemas — Job, EvaluationScore
│   │   ├── loader.py          # CSV loader
│   │   ├── parser.py          # LLM extraction
│   │   ├── postprocess.py     # Deterministic cleanup
│   │   ├── pipeline.py        # Batch orchestrator
│   │   └── hub.py             # HuggingFace Hub push/pull
│   └── evals/
│       ├── judge.py           # LLM-as-a-Judge
│       ├── runner.py          # Eval orchestrator
│       ├── report.py          # Score aggregation
│       ├── eval_trend.py      # Trajectory plots
│       └── human_eval.py      # Human scoring interface
├── tests/
│   ├── test_postprocess.py
│   └── test_pipeline_checkpoint.py
├── eval_results/              # Per-run eval output (committed — anchors prompt history)
├── .github/workflows/ci.yml   # pytest on push
├── pyproject.toml             # pinned dependencies
└── docs/
    └── technical_report.md
```

---

## Documentation

- **[Technical Report](docs/technical_report.md)** — architecture decisions, full prompt version history (v1–v33), evaluation methodology and results, postprocessing design, prompt engineering retrospective
- **[Job Intelligence Engine](https://github.com/AlejandroFuentePinero/job-intelligence-engine)** — the main project this extraction layer feeds into

---

## Author

**Alejandro de la Fuente** · [GitHub](https://github.com/AlejandroFuentePinero) · [LinkedIn](https://www.linkedin.com/in/alejandro-de-la-fuente-a367a137a/)

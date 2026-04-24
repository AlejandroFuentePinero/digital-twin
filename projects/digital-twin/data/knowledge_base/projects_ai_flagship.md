# AI Engineering Projects (Flagship)

---

## 1. LLM Engineering Lab
**GitHub:** https://github.com/AlejandroFuentePinero/llm-engineering-lab
**Tier:** Flagship | Production-grade

A collection of 11 production-minded Python projects spanning the full LLM engineering stack — from structured prompting and RAG to QLoRA fine-tuning, autonomous multi-agent systems, and serverless cloud deployment.

### Flagship project: LLM Price Predictor
An end-to-end ML system that predicts Amazon product prices from natural language descriptions. Covers the full lifecycle across 7 stages:

1. **Data curation** — 820k Amazon products across 8 categories, deduplicated and resampled with quadratic weighting to reduce price-distribution skew. Published to HuggingFace Hub: `Alejandrofupi/items_full` (820k) and `Alejandrofupi/items_lite` (23k).
2. **LLM batch preprocessing** — async Groq batch job generates clean structured summaries for every item; state persisted to disk for resumability.
3. **Fine-tuning preparation** — prompt-completion pairs in SFT format using Llama-3.2-3B tokeniser with 110-token cap.
4. **Modelling and evaluation** — all models evaluated on the same held-out test split with a shared `Tester` class. QLoRA fine-tuning: 4-bit NF4 quantisation on T4 GPU, LoRA adapters on attention and MLP layers. Training logged to Weights & Biases.
5. **RAG pipeline** — 800k training products encoded with `all-MiniLM-L6-v2` and stored in ChromaDB. At inference, 5 most similar products retrieved and passed as context to GPT-5.1.
6. **Ensemble + autonomous agents** — three predictors blended: GPT-5.1+RAG (80%), fine-tuned Modal specialist (10%), DNN (10%). Autonomous agents scan RSS deal feeds (`ScannerAgent`), price each deal via the ensemble (`EnsembleAgent`), and push real-time notifications (`MessagingAgent`). Orchestration lives in the model: `AutonomousPlanningAgent` gives GPT-5.1 three tools and lets it plan autonomously.
7. **Live Gradio dashboard** — streams agent logs in real time, displays deals in a clickable dataframe, renders 3D t-SNE scatter of 800k vectorstore embeddings. Auto-refreshes every 5 minutes.

**Models benchmarked:** constant/linear/RF/XGBoost baselines, 8-layer MLP, 10-layer ResNet, GPT-4.1-nano (zero-shot and fine-tuned), Llama-3.2-3B (base and QLoRA), GPT-5.1+RAG, ensemble.

**Final ensemble result:** MAE **$29.95** and **R² 86.3%** on a held-out test set of 10,000 Amazon products. Ensemble weights: GPT-5.1+RAG (80%), fine-tuned Modal specialist (10%), DNN (10%). The RAG component leads the blend; the specialist and DNN act as anchors dampening outlier predictions.

### Supporting project in depth: Expert Knowledge Worker (RAG Chatbot)

The most technically sophisticated supporting project — and the closest structural analogue to the digital twin. Demonstrates the full RAG engineering and evaluation stack.

**What it does:** A RAG assistant for answering questions about a company knowledge base (Insurellm). Two core pipelines (baseline and optimised), a Gradio chat UI showing both the answer and retrieved source context side-by-side, and a standalone evaluation dashboard.

**Baseline pipeline (LangChain + ChromaDB):**
- Document ingestion: loads Markdown files grouped by subfolder, tags with metadata, splits with recursive text splitter (chunk_size=500, overlap=200), stores in persistent Chroma collection
- Retrieval: k=10, conversation-aware (uses current question + prior user turns to improve retrieval for follow-up questions)
- Answering: retrieved context injected into system prompt, chat model generates grounded response
- UI: chat interface + side panel showing retrieved chunks with source metadata

**Optimised pipeline (direct OpenAI SDK + ChromaDB, no LangChain):**
- LLM-based chunking: instead of fixed-size splits, an LLM reads each document and decides how to chunk it. Each chunk is a structured object with three fields: `headline` (optimised to match query phrasing), `summary` (synthesis of what the chunk answers), `original_text` (verbatim source). All three are concatenated and embedded together — each vector encodes both the dense content and the surface forms most likely to be retrieved.
- Hierarchical RAG: at ingest time, for each subfolder, an LLM reads all documents in that category and produces an aggregated `summary_{category}.md` file. These summaries are designed to answer holistic questions (totals, counts, averages, rankings) that individual chunks can't answer. They're stored in the same ChromaDB collection — the reranker naturally promotes them for holistic queries and demotes them for specific lookups. No changes to the retrieval pipeline needed.
- Query rewriting: user question rewritten into a tighter KB query before retrieval
- Chunk merging: results from original and rewritten queries (k=20 each) deduplicated into one pool
- LLM reranking: a reranker call receives the merged pool and returns a `RankOrder` structured output, re-ordering by relevance before the top k=10 go to the answer model
- Retry logic (tenacity) wraps all LLM calls for rate limit handling

**Evaluation system (standalone dashboard):**
- Retrieval metrics: MRR (mean reciprocal rank), nDCG (position-weighted keyword coverage), keyword coverage percentage — computed per test question against a labelled `tests.jsonl`
- Answer quality: LLM-as-judge (GPT-4.1-nano) scores each response on Accuracy, Completeness, and Relevance (1–5 each) using structured outputs, compared against reference answers
- Gradio evaluation dashboard: colour-coded metrics (green/amber/red) and per-category bar chart
- CLI mode for inspecting individual test cases

**Why it's relevant:** This project directly validates the RAG evaluation pattern Alejandro applies in his own projects (including this digital twin). The hierarchical RAG design, query rewriting, and LLM reranking are the same patterns described in `decisions_and_roadmap.md` as the target for Phase 2 tuning.

**Stack:** Python · OpenAI SDK · LangChain · ChromaDB · LiteLLM · Gradio · tenacity · Pydantic

### Other supporting projects (9)
- **Multi-Agent Conversation:** three-agent review panel (Data Scientist, PM, Tech Lead) demonstrating state drift, role drift, and turn-taking discipline in multi-agent systems
- **Flight Booking Agentic Tool:** tool calling against SQLite (price queries + mock bookings), multi-step agentic loop, TTS audio replies, destination image generation
- **LLM Code Performance Benchmark:** compares OpenAI, Anthropic, Ollama, OpenRouter on Python-to-C++ translation; failure-aware (distinguishes compile error, runtime error, success)
- **Company Brochure Generator:** two-stage pipeline (planning call → generation call) — separates "decide what to read" from "write the output"
- **Meeting Minute Generator:** Whisper transcription → structured Markdown minutes with faithfulness guardrails and transcript persistence
- **Sales Intake Copilot:** B2B lead qualification chatbot producing structured internal handoff notes
- **Synthetic A/B Dataset Generator:** CSV + Markdown dataset card from a schema-as-contract prompt
- **Web Summary Tool:** URL → Markdown brief via OpenAI or Ollama; persona/tone control
- **Tech Tutor:** data/ML/software Q&A with a single movie-analogy backbone thread; OpenAI and Ollama backends

**Stack:** Python · OpenAI · Anthropic · HuggingFace · LangChain · ChromaDB · QLoRA · Modal · Weights & Biases · Gradio · Whisper · Pydantic

### Engineering patterns across the lab

Six patterns applied consistently across all 11 projects — the clearest answer to "what engineering habits have you internalized?":

- **Prompt contracts** — prompts specify tone, length, format, and faithfulness guardrails upfront so outputs are consistent and predictable across runs. The LLM cannot invent what the contract doesn't allow.
- **Stage-based orchestration** — each pipeline stage is an independent module that can be re-run or swapped without touching others. Matters when iterating on a single layer (e.g., testing a different prompt format for fine-tuning without re-running data curation).
- **Evaluation as a first-class concern** — the Price Predictor benchmarks a dozen model families on the same held-out test set with the same `Tester` class; the RAG project measures retrieval quality (MRR, nDCG) and answer quality (LLM-as-judge) in a live dashboard. Evaluation is designed before the model, not added after.
- **Observability by design** — the Gradio dashboard streams agent logs in real time, surfaces results in an inspectable dataframe, and renders the vectorstore embedding geometry in 3D. The full system is observable from a single interface.
- **Workflow-ready outputs** — results are produced as Markdown and structured JSON so they plug into docs, tickets, notes, and downstream tools without manual cleanup.
- **Resumable async jobs** — batch preprocessing (Groq) and fine-tuning (OpenAI) jobs persist state to disk and poll on restart, so 24-hour cloud jobs survive notebook restarts and network interruptions without re-running from scratch.

---

## 2. AI-JIE: LLM Extraction & Evaluation Pipeline
**GitHub:** https://github.com/AlejandroFuentePinero/ai-jie
**HuggingFace dataset:** https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-preprocessed
**Technical report:** https://github.com/AlejandroFuentePinero/ai-jie/blob/main/docs/technical_report.md
**Tier:** Flagship | Production-grade

A structured extraction pipeline that reads raw job postings and produces validated, intent-classified `Job` objects at scale. The core challenge: getting the LLM to reliably distinguish **required** vs **preferred** vs **soft** skills — and to separate genuine skill demands from responsibilities described as skills. Solved through 33 prompt iterations and an architectural shift to chain-of-thought scaffolding.

**What it produces:** Each posting is parsed into a Pydantic-validated `Job` object with skills partitioned by intent, role metadata (seniority, job family, experience, responsibilities), and chain-of-thought intermediate fields. Published dataset covers 3,892 Data Scientist postings.

**Key engineering decisions:**
- **Chain-of-thought scaffolding:** intermediate Pydantic fields (`responsibility_skills_found`, `preferred_signals_found`, `all_technical_skills`) force the model to reason explicitly before classifying. Early flat extraction versions conflated responsibilities with requirements; adding these intermediate reasoning fields was the single largest accuracy gain across all 33 prompt versions.
- **`instructor` library as structural constraint:** extraction uses the `instructor` library on top of the OpenAI SDK — it enforces Pydantic schema validation on every LLM response, making malformed extractions a retry rather than a silent corruption. This turns schema compliance from a hope into a guarantee.
- **Two-model cost separation:** `gpt-5.4-mini` for high-volume extraction (3,892 postings); a separate LLM as independent judge for evaluation — separates cost profile and prevents self-evaluation bias.
- **Async concurrency with checkpointing:** `asyncio` for concurrent extraction; fault-tolerant JSONL checkpointing so batch runs survive interruptions without re-extracting from the beginning. Checkpoint logic is idempotent and corruption-tolerant.
- **Deterministic postprocessing:** rule-based responsibility exclusion and blocklist filtering run after extraction. LLM extracts broadly (deliberately over-inclusive); deterministic layer handles known noise patterns reproducibly. Separating concerns means the LLM doesn't have to be perfect — the postprocessor handles what it gets consistently wrong.

**Evaluation methodology:**
- **LLM-as-judge:** 1–3 scale across multiple extraction dimensions, n=50 fixed random sample (seed=42), tracked across all 33 prompt versions. Architectural baseline (v9g) achieved 2.98/3.00. All eval runs committed to `eval_results/` as permanent prompt history.
- **Human evaluation:** 28-posting sample scored 1–5 across 9 dimensions by independent human rater. Overall 4.11/5.00; structural fields near-perfect (seniority 5.00, responsibilities 5.00). Weakest dimension: skills_required 4.00/5.00 (residual noise handled by postprocessing).
- **Inter-rater agreement:** Cohen's kappa computed across human evaluation dimensions.
- **HuggingFace Hub pipeline:** preprocessed and postprocessed datasets published separately — preprocessed retains chain-of-thought scaffolding fields; postprocessed has them stripped with blocklist applied.

**Production engineering:**
- GitHub Actions CI runs `pytest` on every push
- Unit tests cover: deterministic postprocessing (`apply_responsibility_exclusion`, `_remove_blocked`, consistency across `postprocess()` / `postprocess_df()`), pipeline checkpoint/resume logic (idempotency, no duplicates, corrupt-line tolerance)
- `pyproject.toml` with pinned dependencies; Python 3.13+

**Stack:** Python · OpenAI API (`gpt-5.4-mini`) · `instructor` · Pydantic · asyncio · HuggingFace Hub · pytest · GitHub Actions

---

## 3. Job Intelligence Engine
**Live app:** https://job-intelligence-engine.streamlit.app/
**GitHub:** https://github.com/AlejandroFuentePinero/job-intelligence-engine
**Tier:** Flagship | Deployed app

A deterministic job-market intelligence system that turns raw job postings into interpretable skill demand, salary signals, and clear best-now vs stretch recommendations.

**Problem:** Job postings are noisy — roles and skills overlap heavily in meaning, the same requirements appear in different language, and "fit" devolves into keyword matching. The result is wasted time applying to roles that are either unrealistic or undershoot your potential.

**What it delivers:**
- **Interpretable market signals:** structured skill demand and salary drivers you can inspect and reason about
- **Career positioning:** separates `best_now` roles (strong fit, low barriers) from `stretch` roles (higher upside, clear gaps), with explicit rationale
- **Upskilling recommendations:** counterfactual "add-one-skill" analysis ranking what to learn by the change in suitability, competitiveness, and salary alignment

**Pipeline architecture (5 stages):**
1. **Normalisation** — raw postings are cleaned into a consistent dataset: title standardisation, seniority inference, location/sector metadata, salary field parsing and imputation, skill token extraction from unstructured text.
2. **Market learning** — two models learn the market's structure from the normalised data: a *probabilistic skill-requirement model* smooths noisy binary skill keywords into calibrated per-job skill-demand probabilities (reducing keyword noise without losing signal); a *salary response model* (XGBoost/LightGBM + SHAP) captures how job attributes and skill combinations relate to compensation.
3. **Profile mapping** — the user's current skill profile is embedded into the same skill space as the jobs using SBERT semantic embeddings, enabling like-for-like comparison between user profile and job requirements.
4. **Suitability vs. competitiveness separation** — the engine keeps two signals distinct: *suitability* (how well the current profile fits a job's requirements) and *competitiveness* (the barrier to entry set by missing skills, rare requirements, and seniority/pay expectations). Most job tools collapse these into a single score; separating them is what makes `best_now` vs `stretch` recommendations meaningful. `Best-now` = high suitability + low competitiveness barrier. `Stretch` = high directional fit + clear gaps that are closeable.
5. **Counterfactual upskilling** — hold the job universe constant, simulate adding each missing skill family to the user's profile one at a time, recompute positioning, and rank skills by observed lift. Lift includes both direct suitability improvement and "stretch → best-now promotion" effects (how many roles move from out-of-reach to realistic). Skills are penalised if they harm the existing best-now set. Result: an ROI-ranked upskilling plan grounded in observed job-posting demand, not generic advice.

**Stack:** Python · pandas · NumPy · scikit-learn · SBERT · XGBoost/LightGBM · SHAP · Streamlit · NetworkX

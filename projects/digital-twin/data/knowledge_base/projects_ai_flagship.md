# AI Engineering Projects (Flagship)

---

## LLM Engineering Lab — Overview
**GitHub:** https://github.com/AlejandroFuentePinero/llm-engineering-lab
**Tier:** Flagship | Production-grade

A collection of 11 production-minded Python projects spanning the full LLM engineering stack — from structured prompting and RAG to QLoRA fine-tuning, autonomous multi-agent systems, and serverless cloud deployment.

**Stack:** Python · OpenAI · Anthropic · HuggingFace · LangChain · ChromaDB · QLoRA · Modal · Weights & Biases · Gradio · Whisper · Pydantic

---

## LLM Price Predictor
*Part of LLM Engineering Lab — flagship project*

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

---

## LLM Price Predictor — Autonomous Agent System
*Part of LLM Engineering Lab — flagship project*

The autonomous layer of the LLM Price Predictor is a production agentic AI system where an LLM orchestrates specialised agents in a continuous, self-directed deal-monitoring loop.

**AutonomousPlanningAgent** equips GPT-5.1 with three callable tools and lets it plan the workflow autonomously — no hard-coded routing or fixed step order. The model decides when to scan for deals, when to price them, and when to send notifications.

**Three specialised agents:**
- **ScannerAgent** — monitors live RSS deal feeds for new Amazon product listings
- **EnsembleAgent** — prices each deal via the full ensemble (GPT-5.1+RAG 80%, fine-tuned Modal specialist 10%, DNN 10%)
- **MessagingAgent** — pushes real-time price-alert notifications when deals are flagged

**Agentic design patterns demonstrated:**
- **LLM-as-planner:** the orchestration model has no fixed workflow; it reasons about which tool to call next and in what order
- **Tool use:** planning agent is given three callable tools that wrap the specialised agents
- **Continuous operation:** the loop runs autonomously, auto-refreshing on a schedule
- **Observability:** agent decision logs stream in real time to a live Gradio dashboard; results displayed in an inspectable dataframe

**Stack:** Python · GPT-5.1 · tool calling · Modal (serverless fine-tuned specialist) · Gradio

---

## Expert Knowledge Worker (RAG Chatbot)
*Part of LLM Engineering Lab — most technically sophisticated supporting project*

A RAG assistant for answering questions about a company knowledge base (Insurellm). Two core pipelines (baseline and optimised), a Gradio chat UI showing both the answer and retrieved source context side-by-side, and a standalone evaluation dashboard.

**Baseline pipeline (LangChain + ChromaDB):**
- Document ingestion: loads Markdown files grouped by subfolder, tags with metadata, splits with recursive text splitter (chunk_size=500, overlap=200), stores in persistent Chroma collection
- Retrieval: k=10, conversation-aware (uses current question + prior user turns to improve retrieval for follow-up questions)
- Answering: retrieved context injected into system prompt, chat model generates grounded response
- UI: chat interface + side panel showing retrieved chunks with source metadata

**Optimised pipeline (direct OpenAI SDK + ChromaDB, no LangChain):**
- LLM-based chunking: instead of fixed-size splits, an LLM reads each document and decides how to chunk it. Each chunk is a structured object with three fields: `headline` (optimised to match query phrasing), `summary` (synthesis of what the chunk answers), `original_text` (verbatim source). All three are concatenated and embedded together.
- Hierarchical RAG: category-level summary chunks for holistic queries; LLM reranking; query rewriting; chunk merging from dual retrieval passes.

**Evaluation system:** MRR, nDCG, keyword coverage for retrieval; LLM-as-judge for answer quality (Accuracy, Completeness, Relevance 1–5). Gradio evaluation dashboard with colour-coded metrics.

**Why it's relevant:** This project directly validates the RAG evaluation pattern Alejandro applies in his own projects. The hierarchical RAG design, query rewriting, and LLM reranking are the same patterns described in the digital twin architecture.

**Stack:** Python · OpenAI SDK · LangChain · ChromaDB · LiteLLM · Gradio · tenacity · Pydantic

---

## Other Supporting Projects (LLM Engineering Lab)
*9 additional projects in the LLM Engineering Lab*

- **Multi-Agent Conversation:** three-agent review panel (Data Scientist, PM, Tech Lead) demonstrating state drift, role drift, and turn-taking discipline in multi-agent systems
- **Flight Booking Agentic Tool:** tool calling against SQLite (price queries + mock bookings), multi-step agentic loop, TTS audio replies, destination image generation
- **LLM Code Performance Benchmark:** compares OpenAI, Anthropic, Ollama, OpenRouter on Python-to-C++ translation; failure-aware (distinguishes compile error, runtime error, success)
- **Company Brochure Generator:** two-stage pipeline (planning call → generation call) — separates "decide what to read" from "write the output"
- **Meeting Minute Generator:** Whisper transcription → structured Markdown minutes with faithfulness guardrails and transcript persistence
- **Sales Intake Copilot:** B2B lead qualification chatbot producing structured internal handoff notes
- **Synthetic A/B Dataset Generator:** CSV + Markdown dataset card from a schema-as-contract prompt
- **Web Summary Tool:** URL → Markdown brief via OpenAI or Ollama; persona/tone control
- **Tech Tutor:** data/ML/software Q&A with a single movie-analogy backbone thread; OpenAI and Ollama backends

---

## Engineering Patterns (LLM Engineering Lab)

Six patterns applied consistently across all 11 projects — the clearest answer to "what engineering habits have you internalized?":

- **Prompt contracts** — prompts specify tone, length, format, and faithfulness guardrails upfront so outputs are consistent and predictable across runs.
- **Stage-based orchestration** — each pipeline stage is an independent module that can be re-run or swapped without touching others.
- **Evaluation as a first-class concern** — the Price Predictor benchmarks a dozen model families on the same held-out test set with the same `Tester` class; the RAG project measures retrieval quality (MRR, nDCG) and answer quality (LLM-as-judge) in a live dashboard. Evaluation is designed before the model, not added after.
- **Observability by design** — the Gradio dashboard streams agent logs in real time, surfaces results in an inspectable dataframe, and renders the vectorstore embedding geometry in 3D.
- **Workflow-ready outputs** — results are produced as Markdown and structured JSON so they plug into docs, tickets, notes, and downstream tools without manual cleanup.
- **Resumable async jobs** — batch preprocessing (Groq) and fine-tuning (OpenAI) jobs persist state to disk and poll on restart, so 24-hour cloud jobs survive notebook restarts and network interruptions.

---

## AI-JIE: LLM Extraction & Evaluation Pipeline
**GitHub:** https://github.com/AlejandroFuentePinero/ai-jie
**HuggingFace dataset:** https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-preprocessed
**Technical report:** https://github.com/AlejandroFuentePinero/ai-jie/blob/main/docs/technical_report.md
**Tier:** Flagship | Production-grade

A structured extraction pipeline that reads raw job postings and produces validated, intent-classified `Job` objects at scale. The core challenge: getting the LLM to reliably distinguish **required** vs **preferred** vs **soft** skills — and to separate genuine skill demands from responsibilities described as skills. Solved through 33 prompt iterations and an architectural shift to chain-of-thought scaffolding.

**What it produces:** Each posting is parsed into a Pydantic-validated `Job` object with skills partitioned by intent, role metadata (seniority, job family, experience, responsibilities), and chain-of-thought intermediate fields. Published dataset covers 3,892 Data Scientist postings.

**Key engineering decisions:**
- **Chain-of-thought scaffolding:** Early prompt versions asked the model to directly classify skills into required/preferred/soft. Accuracy on preferred skills was poor — the model conflated responsibilities with requirements. The fix was adding intermediate Pydantic fields (`responsibility_skills_found`, `preferred_signals_found`, `all_technical_skills`) that force explicit reasoning before classification. This single architectural change was the largest accuracy gain across all 33 prompt versions.
- **`instructor` library as structural constraint:** enforces Pydantic schema validation on every LLM response, making malformed extractions a retry rather than a silent corruption.
- **Two-model cost separation:** `gpt-5.4-mini` for high-volume extraction; a separate LLM as independent judge for evaluation — separates cost profile and prevents self-evaluation bias.
- **Async concurrency with checkpointing:** `asyncio` for concurrent extraction; fault-tolerant JSONL checkpointing so batch runs survive interruptions.
- **Deterministic postprocessing:** rule-based responsibility exclusion and blocklist filtering run after extraction. LLM extracts broadly; deterministic layer handles known noise patterns reproducibly.

**Evaluation methodology:**
- **LLM-as-judge:** 1–3 scale across multiple extraction dimensions, n=50 fixed random sample (seed=42), tracked across all 33 prompt versions. Architectural baseline (v9g) achieved 2.98/3.00.
- **Human evaluation:** 28-posting sample scored 1–5 across 9 dimensions by independent human rater. Overall 4.11/5.00; structural fields near-perfect (seniority 5.00, responsibilities 5.00).
- **Inter-rater agreement:** Cohen's kappa computed across human evaluation dimensions.
- **HuggingFace Hub pipeline:** preprocessed and postprocessed datasets published separately.

**Production engineering:** GitHub Actions CI, pytest unit tests covering postprocessing idempotency and checkpoint/resume logic, `pyproject.toml` with pinned dependencies, Python 3.13+.

**Stack:** Python · OpenAI API (`gpt-5.4-mini`) · `instructor` · Pydantic · asyncio · HuggingFace Hub · pytest · GitHub Actions

---

## Job Intelligence Engine
**Live app:** https://job-intelligence-engine.streamlit.app/
**GitHub:** https://github.com/AlejandroFuentePinero/job-intelligence-engine
**Tier:** Flagship | Deployed app

A deterministic job-market intelligence system that turns raw job postings into interpretable skill demand, salary signals, and clear best-now vs stretch recommendations.

**Problem:** Job postings are noisy — roles and skills overlap heavily in meaning, the same requirements appear in different language, and "fit" devolves into keyword matching.

**What it delivers:**
- **Interpretable market signals:** structured skill demand and salary drivers you can inspect and reason about
- **Career positioning:** separates `best_now` roles (strong fit, low barriers) from `stretch` roles (higher upside, clear gaps), with explicit rationale
- **Upskilling recommendations:** counterfactual "add-one-skill" analysis ranking what to learn by the change in suitability, competitiveness, and salary alignment

**Pipeline architecture (5 stages):**
1. **Normalisation** — title standardisation, seniority inference, location/sector metadata, salary field parsing and imputation, skill token extraction.
2. **Market learning** — probabilistic skill-requirement model smooths noisy binary skill keywords into calibrated per-job skill-demand probabilities; salary response model (XGBoost/LightGBM + SHAP) captures how job attributes and skill combinations relate to compensation.
3. **Profile mapping** — user's current skill profile embedded into the same skill space as the jobs using SBERT semantic embeddings, enabling like-for-like comparison.
4. **Suitability vs. competitiveness separation** — *suitability* (how well the current profile fits requirements) and *competitiveness* (barrier to entry set by missing skills) are kept distinct. `Best-now` = high suitability + low competitiveness barrier. `Stretch` = high directional fit + clear closeable gaps.
5. **Counterfactual upskilling** — hold the job universe constant, simulate adding each missing skill family one at a time, recompute positioning, and rank skills by observed lift including "stretch → best-now promotion" effects.

**Stack:** Python · pandas · NumPy · scikit-learn · SBERT · XGBoost/LightGBM · SHAP · Streamlit · NetworkX

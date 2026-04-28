---
title: "LLM Engineering Lab"
excerpt: "Eleven production-minded Python projects spanning the full LLM engineering stack — from structured prompting and RAG to QLoRA fine-tuning, autonomous multi-agent systems, and serverless cloud deployment. The flagship project builds a price predictor that trains on 800k products, benchmarks a dozen model architectures, and deploys an autonomous agent that scans for deals and notifies you in real time."
date: 2026-03-25
tier: featured   # featured | learning | research
order: 3
---

<p align="center">
  <img src="/files/llm-engineering-cartoon.png" alt="LLM Engineering Lab" width="900">
</p>

## Motivation

This lab is my sandbox for building LLM systems that hold up in real work. Projects escalate in complexity: the earlier ones establish core patterns — structured prompting, retrieval, tool use — and the later ones bring everything together into production-grade systems with data pipelines, model training, cloud deployment, and autonomous agents. The emphasis throughout is engineering judgement: when to chain calls, how to constrain prompts for consistency, and how to produce artefacts that integrate cleanly into downstream workflows.

**[→ Explore the full repo on GitHub](https://github.com/AlejandroFuentePinero/llm-engineering-lab)**

---

## Flagship project: LLM Price Predictor

An end-to-end ML system that predicts Amazon product prices from natural language descriptions. It covers the full lifecycle — data curation at scale, LLM-powered preprocessing, model training and benchmarking across a dozen architectures, RAG retrieval, cloud deployment, autonomous multi-agent orchestration, and a live Gradio dashboard — and culminates in an agent that scans the web for deals, prices them using the ensemble model, and notifies the user in real time.

### The pipeline in seven stages

**1. Data curation** — 820k Amazon products ingested across 8 categories, filtered, deduplicated, and resampled using quadratic weighting to reduce price-distribution skew. Both a full (~820k) and lite (~23k) dataset are pushed to HuggingFace Hub.

**2. LLM batch preprocessing** — product descriptions are noisy. An async Groq batch job generates clean structured summaries (Title / Category / Brand / Description / Details) for every item before any model sees the data. State is persisted to disk so long-running jobs survive restarts without data loss.

**3. Fine-tuning preparation** — prompt-completion pairs are generated in SFT format using the Llama-3.2-3B tokeniser with a 110-token cap, then pushed to HuggingFace Hub for training.

**4. Modelling and evaluation** — all models are evaluated on the same held-out test split with the same `Tester` class, keeping the comparison fair across model families. Open-source fine-tuning uses QLoRA: 4-bit NF4 quantisation on a T4 GPU, with LoRA adapters trained on attention (lite) and attention + MLP layers (full). Training is logged to Weights & Biases.

**5. RAG pipeline** — all 800k training products are encoded with `sentence-transformers/all-MiniLM-L6-v2` and stored in ChromaDB. At inference time, the 5 most similar products are retrieved and passed as context to GPT-5.1, grounding predictions in real comparable products.

**6. Ensemble + agent system** — three predictors are blended: GPT-5.1+RAG (80%), the fine-tuned Modal specialist (10%), and the DNN (10%). On top of this sits an autonomous agent that:
- scrapes RSS deal feeds via `ScannerAgent`, filtering for deals with clear prices and descriptions
- prices each deal using the ensemble via `EnsembleAgent`
- picks the best opportunity and triggers a real-time push notification via `MessagingAgent` (Pushover API)

The orchestration logic lives in the model, not in code: `AutonomousPlanningAgent` gives GPT-5.1 three tools (`scan_the_internet_for_bargains`, `estimate_true_value`, `notify_user_of_deal`) and lets it decide the plan autonomously.

**7. Live dashboard** — a Gradio UI that runs the deal-finding agent on load and auto-refreshes every 5 minutes. Streams agent logs to the UI in real time via a background thread and queue; displays found deals in a clickable dataframe (click to re-trigger a push notification); renders a 3D t-SNE scatter plot of the 800k vectorstore embeddings coloured by product category. The full system is observable end-to-end from a single interface.

### Models benchmarked

| Model | Type |
|---|---|
| Constant / Linear / Random Forest / XGBoost | Traditional ML baselines |
| Neural Network (8-layer MLP) | Deep learning |
| Deep Neural Network (10-layer ResNet, log-space) | Deep learning |
| GPT-4.1 Nano (zero-shot) | Frontier LLM, pre-trained |
| GPT-4.1 Nano (fine-tuned) | Frontier LLM, fine-tuned |
| Llama-3.2-3B (base) | Open-source LLM, pre-trained |
| Llama-3.2-3B (fine-tuned, QLoRA) | Open-source LLM, fine-tuned |
| GPT-5.1 + RAG | Frontier LLM with retrieval augmentation |
| Ensemble (GPT-5.1+RAG + specialist + DNN) | Multi-model ensemble |

---

## Supporting projects

Each of the ten supporting projects isolates a specific pattern (retrieval, tool-calling, evaluation, multimodal) that feeds into the flagship.

**Expert Knowledge Worker (RAG Chatbot)** — A RAG assistant over a Markdown knowledge base. Separates ingestion (chunking, embedding, Chroma) from answering (conversation-aware retrieval + generation), with a Gradio UI that shows retrieved source chunks side-by-side with the answer. Includes a full evaluation suite: retrieval quality (MRR, nDCG, keyword coverage) and LLM-as-judge answer scoring (accuracy, completeness, relevance) in a colour-coded dashboard.

**Multi-Agent Conversation** — A turn-based three-agent review panel (Data Scientist, PM, Tech Lead) sharing a single conversation transcript as the source of truth. Designed to expose the core pitfalls of multi-agent systems: state drift, role drift, and inconsistent turn-taking.

**Flight Booking Agentic Tool** — A chat agent with real tool-calling against a SQLite backend: price queries and mock bookings with autoincrement IDs. Demonstrates the full tool-call loop — schema-constrained invocations appended back into message history, multi-step resolution — plus TTS audio replies and destination image generation.

**LLM Code Performance Benchmark** — Compares hosted (OpenAI, Anthropic) and open-source (Ollama, OpenRouter) models on Python-to-C++ translation, measuring runtime speedup and distinguishing failure modes (compile error, runtime error, success). Every model's C++ output is saved as an artefact.

**Company Brochure Generator** — Two-stage pipeline: a planning call selects the most brochure-relevant pages, a generation call synthesises the brief. Demonstrates how separating "decide what to read" from "write the output" reduces noise and keeps generations grounded.

**Meeting Minute Generator** — Whisper transcription → structured Markdown minutes with a fixed, contract-driven format. Faithfulness guardrails prevent invented metadata; transcript persistence allows debugging at the transcription vs. summarisation level.

**Sales Intake Copilot** — A B2B lead-qualification chatbot that produces a structured handoff note for a human rep, demonstrating conversational intake on the front-end with consistent operational artefacts on the back-end.

**Synthetic A/B Dataset Generator** — Generates a CSV conversion dataset and a Markdown dataset card from a schema-as-contract prompt. Useful for prototyping dashboards, testing pipelines, and teaching experimentation.

**Web Summary Tool** — URL → Markdown brief via OpenAI or Ollama. A `chat_personality` parameter adapts tone for different audiences.

**Tech Tutor** — Answers data/ML/software questions with a movie-analogy backbone for memorability. Supports OpenAI and Ollama backends with streaming.

---

## Skills demonstrated — by project

This table maps the skills built across the lab to the projects that exercise them. The LLM Price Predictor is where most of them converge.

| Skill | Projects |
|---|---|
| **RAG** (vector ingestion, embedding search, retrieval-augmented generation at scale) | LLM Price Predictor (800k docs, ChromaDB), Expert Knowledge Worker (LangChain + Chroma, hierarchical RAG, query rewriting, LLM reranking) |
| **LLM fine-tuning** (QLoRA open-source, frontier model fine-tuning via API) | LLM Price Predictor (Llama 3.2 3B QLoRA on Colab T4, GPT-4.1-nano fine-tuning via OpenAI API) |
| **Autonomous agents & orchestration** (tool-use, planning loops, multi-agent coordination) | LLM Price Predictor (AutonomousPlanningAgent, ScannerAgent, EnsembleAgent, MessagingAgent), Multi-Agent Conversation, Flight Booking Agentic Tool |
| **LLM evaluation & benchmarking** (model comparison, retrieval metrics, LLM-as-judge) | LLM Price Predictor (dozen model families, shared Tester, W&B logging), Expert Knowledge Worker (MRR, nDCG, LLM-as-judge scoring dashboard), LLM Code Performance Benchmark (multi-provider, failure-aware) |
| **Data engineering at scale** (curation pipelines, deduplication, weighted resampling) | LLM Price Predictor (820k products, async batch preprocessing, HuggingFace Hub) |
| **Cloud & serverless deployment** (Modal, HuggingFace Hub, async batch jobs) | LLM Price Predictor (Modal specialist deployment, Groq async batch API, HF Hub push/pull) |
| **Multi-step LLM pipelines** (planning → generation, prompt contracts) | Company Brochure Generator, LLM Price Predictor, Expert Knowledge Worker |
| **Multimodal** (audio transcription, TTS, image generation) | Meeting Minute Generator (Whisper), Flight Booking Agentic Tool (TTS + image), LLM Price Predictor (vision in frontier models) |
| **Structured outputs** (Pydantic, schema-as-contract, JSON tool schemas) | LLM Price Predictor (Item data model), Flight Booking Agentic Tool (tool schemas), Synthetic A/B Dataset Generator |
| **Observability & deployment** (real-time log streaming, background threads, t-SNE visualisation) | LLM Price Predictor (Gradio live dashboard) |
| **Prompt engineering** (tone control, faithfulness guardrails, persona design) | All projects |

---

## Engineering patterns across the lab

- **Prompt contracts** — prompts specify tone, length, format, and faithfulness guardrails so outputs are consistent and predictable across runs.
- **Stage-based orchestration** — each pipeline stage is an independent module that can be re-run or swapped without touching the others. Matters when iterating on a single layer (e.g., testing a different prompt format for fine-tuning).
- **Evaluation as a first-class concern** — the Price Predictor benchmarks a dozen model families on the same held-out test set; the RAG project measures both retrieval quality (MRR, nDCG) and answer quality (LLM-as-judge) in a live dashboard.
- **Observability by design** — the live Gradio dashboard streams agent logs in real time, surfaces deal results in an interactive dataframe, and renders the vectorstore geometry in 3D. The full system is inspectable from a single interface.
- **Workflow-ready outputs** — results are produced as Markdown and structured JSON so they plug into docs, tickets, wikis, and downstream tools without manual cleanup.
- **Resumable async jobs** — batch preprocessing and fine-tuning jobs persist state to disk and poll on restart, so 24-hour cloud jobs survive interruptions.
- **Environment portability** — utilities run against hosted or local models (OpenAI / Anthropic / Ollama / OpenRouter) via the same interfaces.

## Links & Resources
- **Code repository:** [GitHub – LLM Engineering Lab](https://github.com/AlejandroFuentePinero/llm-engineering-lab)

# LLM Engineering Lab

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab

## What it is

A portfolio of 11 production-grade LLM systems built from scratch — spanning RAG at 800k-document scale, open-source and frontier model fine-tuning, multi-agent orchestration, autonomous planning, and serverless cloud deployment. Every project is end-to-end: real data, real evaluation, real infrastructure. Projects escalate in complexity: earlier ones establish core patterns (structured prompting, retrieval, tool use); the flagship (LLM Price Predictor) brings everything together as a single end-to-end agentic system.

The 11 projects in this monorepo each have their own distilled README in this registry — fetch the specific one for implementation depth on any single project.

## Architecture (skills demonstrated across the lab)

- **RAG** — vector ingestion, embedding search, retrieval-augmented generation at 800k-document scale (LLM Price Predictor); LLM-based chunking, query rewriting, hierarchical RAG, and LLM reranking (Expert Knowledge Worker).
- **Fine-tuning** — QLoRA fine-tuning of open-source LLMs (Llama-3.2-3B) on Colab T4 GPUs; frontier model fine-tuning via OpenAI API (gpt-4.1-nano).
- **Agents and orchestration** — tool-use agents, autonomous planning loops where the LLM decides workflow at runtime (no hard-coded routing), multi-agent coordination, real-time deal detection and notification.
- **Cloud deployment** — Modal serverless deployment for fine-tuned specialists; HuggingFace Hub integration for datasets and model artefacts; async batch jobs (Groq) with checkpoint/resume.
- **Multimodal** — vision and voice capabilities across select projects (Whisper transcription, image generation, TTS).
- **Evaluation** — rigorous benchmarking across a dozen model families on the same held-out test set with a shared `Tester` class; LLM-as-judge with structured outputs and inter-rater calibration.

## Key engineering patterns (recurring across all 11 projects)

- **Prompt contracts** — prompts specify tone, length, format, and faithfulness guardrails upfront so outputs are consistent and predictable across runs.
- **Stage-based orchestration** — each pipeline stage is an independent module that can be re-run or swapped without touching others. Matters most when iterating on a single layer (e.g., testing a different prompt format for fine-tuning).
- **Evaluation as a first-class concern** — Price Predictor benchmarks a dozen model families on the same held-out test set with the same `Tester` class; RAG project measures retrieval quality (MRR, nDCG) and answer quality (LLM-as-judge) in a live dashboard. Evaluation is designed before the model, not added after.
- **Observability by design** — Gradio dashboards stream agent logs in real time, surface results in inspectable dataframes, and render the vectorstore embedding geometry in 3D (t-SNE).
- **Workflow-ready outputs** — results produced as Markdown and structured JSON so they plug into docs, tickets, notes, and downstream tools without manual cleanup.
- **Resumable async jobs** — batch preprocessing (Groq) and fine-tuning (OpenAI) jobs persist state to disk and poll on restart, so 24-hour cloud jobs survive notebook restarts and network interruptions.

## Project list (each has its own distilled doc)

| Key | Project | Tier |
|---|---|---|
| `llm_price_predictor` | LLM Price Predictor (820k Amazon products, full ML lifecycle, autonomous agent system) | Flagship |
| `expert_knowledge_worker` | Expert Knowledge Worker (RAG chatbot with optimised hierarchical pipeline) | Most technically sophisticated supporting project |
| `web_summary_tool` | Web Summary Tool | Supporting |
| `company_brochure_generator` | Company Brochure Generator (two-stage select-then-generate) | Supporting |
| `tech_tutor` | Tech Tutor (movie-analogy backbone for memorable explanations) | Supporting |
| `multi_agent_conversation` | Multi-Agent Conversation (3-agent review panel) | Supporting |
| `sales_intake_copilot` | Sales Intake Copilot (B2B lead qualification + handoff note) | Supporting |
| `flight_booking_agentic_tool` | Flight Booking Agentic Tool (tool-calling against SQLite) | Supporting |
| `meeting_minute_generator` | Meeting Minute Generator (Whisper + faithfulness guardrails) | Supporting |
| `synthetic_ab_dataset_generator` | Synthetic A/B Dataset Generator | Supporting |
| `llm_code_performance_benchmark` | LLM Code Performance Benchmark (Python→C++ speedup, multi-provider) | Supporting |

## Stack

Python · OpenAI · Anthropic · HuggingFace · LangChain · ChromaDB · QLoRA · Modal · Weights & Biases · Gradio · Whisper · Pydantic · LiteLLM

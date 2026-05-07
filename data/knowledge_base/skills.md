# Skills and Technical Stack

## Core strength
Statistical modelling and uncertainty-aware inference — particularly Bayesian hierarchical methods — applied to problems where data are noisy, sparse, biased, or structured across space and time. This foundation shapes everything: careful assumptions, principled model selection, rigorous validation, and outputs that are honest about what they do and don't know. The same rigour has been extended into AI engineering.

## What Alejandro delivers
- **End-to-end AI systems:** RAG pipelines with retrieval evaluation (MRR, nDCG, LLM-as-judge), agentic workflows with tool calling and stateful backends, fine-tuned models (frontier SFT and QLoRA for open-source LLMs)
- **Full-cycle ML and modelling:** problem framing, feature engineering, model selection, rigorous validation, and reproducible delivery — with depth in Bayesian hierarchical inference and spatiotemporal forecasting
- **Data pipelines and analytics:** clean, testable, version-controlled pipelines from raw data to decision-ready outputs
- **Evaluation and communication:** leakage checks, calibration, error slicing, robustness testing — results communicated with explicit assumptions, trade-offs, and clear recommendations

---

## AI / LLM Stack
- **APIs & models:** OpenAI, Anthropic (Claude), Google Gemini, HuggingFace
- **Frameworks:** LangChain, LangGraph, instructor
- **Vector stores:** ChromaDB
- **RAG:** full pipeline design — chunking, embedding, retrieval, reranking, evaluation (MRR, nDCG, LLM-as-judge)
- **Multi-LLM orchestration:** classify-then-route pipelines with cross-family generator/judge separation (OpenAI generator + Anthropic guardrail), structured rejection-feedback retry loops, deterministic short-circuit floors on canonical refusal phrases
- **Fine-tuning (frontier):** supervised fine-tuning of closed models via OpenAI and Anthropic APIs
- **Fine-tuning (open-source):** QLoRA — 4-bit NF4/LoRA on Llama 3.2 3B; training tracked in Weights & Biases
- **Agents:** tool calling, planning/acting loops, multi-agent orchestration, human-in-the-loop checkpoints
- **Structured outputs:** Pydantic, schema-as-contract, JSON tool schemas
- **Deployment:** Modal (serverless), Gradio, Streamlit, HuggingFace Spaces (deploy via Hub API; private HF Datasets as durable production log store with buffered + SIGTERM-safe writers)
- **Observability:** Weights & Biases (W&B); custom Gradio operator dashboards over enriched JSONL logs (14 metrics across outcome / routing / latency, failure feed with pipeline replay, KB coverage, drift detection)
- **Drift detection / canary testing:** probe-corpus replay against frozen baselines; outcome-based drift kinds (branch / event_type / outcome / keyword_coverage / red_flag / latency)
- **Multimodal:** text, image, and audio processing in LLM pipelines (Whisper, TTS, vision)

## ML / Data Stack
- **Python:** pandas, NumPy, scikit-learn, XGBoost, LightGBM, TensorFlow/Keras
- **SQL:** PostgreSQL (advanced: window functions, CTEs, recursive queries, analytical patterns)
- **R:** tidyverse, ggplot2, Shiny; Bayesian modelling in JAGS/WinBUGS
- **Embeddings & NLP:** SBERT, sentence-transformers, TF-IDF, semantic search
- **Recommenders:** similarity metrics, collaborative filtering, constraint-aware framing
- **Geospatial:** raster/vector workflows, spatial joins, landscape metrics
- **Visualization:** matplotlib, seaborn, plotly, ggplot2

## Statistical Methods
- Bayesian & hierarchical modelling; partial pooling; uncertainty quantification and propagation
- Spatiotemporal modelling: structured dependence, forecasting logic
- Species distribution modelling (SDMs); N-mixture models; integrated population models (IPMs)
- Supervised learning: regression, classification, gradient boosting, random forests, SVM, k-NN
- Unsupervised learning: PCA, K-Means, anomaly detection
- A/B testing; causal inference; counterfactual framing
- Evaluation: cross-validation, temporal/blocked splits, calibration, SHAP interpretability

## Software Engineering & Cloud
- Git/GitHub: branching, PRs, code review, merge discipline
- Modular architecture, clean interfaces, reusable components, pipeline-style structure
- Quality controls: input validation, assertions, unit tests (pytest), type hints
- Reproducibility: environment management, deterministic runs, versioned artefacts
- **AWS Certified Cloud Practitioner (2026):** EC2, Lambda, S3, RDS, DynamoDB, VPC, IAM, CloudWatch

## Languages
- Spanish (native)
- English (IELTS 7.0, professional)
- French (basic)

## What transfers from research
- **First-principles thinking:** breaking open-ended problems into well-formed questions
- **Measurement discipline:** sampling protocols, data quality, bias and missingness at source
- **Delivery under real constraints:** scoping work, managing trade-offs, shipping on time
- **Transparent communication:** clear, auditable narratives with explicit assumptions and limitations
- **Cross-functional collaboration:** working across disciplines, mentoring, building alignment through structured writing

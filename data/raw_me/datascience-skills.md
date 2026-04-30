---
title: "Skills"
permalink: /datascience/skills/
layout: archive
author_profile: true
classes: wide projects-page
---

## What I'm best at

My core strength is statistical modelling and uncertainty-aware inference (particularly Bayesian hierarchical methods) applied to problems where data are noisy, sparse, biased, or structured across space and time. That foundation shapes everything: careful assumptions, principled model selection, rigorous validation, and outputs that are honest about what they do and don't know.

I've extended that same rigour into AI engineering: building LLM-powered applications, RAG systems with proper evaluation, agentic workflows, and fine-tuned models. The instincts transfer directly: if it can't be evaluated, it can't be trusted, whether that's a Bayesian forecast or an LLM pipeline.

---

## What I deliver

- **End-to-end AI systems:** RAG pipelines with retrieval evaluation (MRR, nDCG, LLM-as-judge), agentic workflows with tool calling and stateful backends, and fine-tuned models (Frontier supervised fine-tuning and QLoRA for open-source LLMs) — built with structured outputs and production habits from the start.
- **Full-cycle ML and modelling:** problem framing, feature engineering, model selection, rigorous validation, and reproducible delivery — with particular depth in Bayesian hierarchical inference, spatiotemporal forecasting, and uncertainty-aware decision support.
- **Data pipelines and analytics:** clean, testable, version-controlled pipelines from raw data to decision-ready outputs, with SQL and Python as the core tools.
- **Evaluation and communication:** leakage checks, calibration, error slicing, robustness testing — and results communicated with explicit assumptions, trade-offs, and clear recommendations.

---

## Core stack

**AI / LLM**
OpenAI · Anthropic · Google · HuggingFace · LangChain · LangGraph · ChromaDB · RAG pipelines · QLoRA fine-tuning (Llama 3.2, 4-bit NF4/LoRA) · Frontier fine-tuning · tool calling · agent orchestration · multimodal inputs (text, image, audio) · Modal serverless deployment · Weights & Biases · Gradio · Streamlit

**ML / Data**
Python (pandas, NumPy, scikit-learn, XGBoost, TensorFlow/Keras, PyTorch) · SQL (PostgreSQL) · R (tidyverse) · Git/GitHub

**Methods**
Bayesian & hierarchical modelling · spatiotemporal forecasting · supervised/unsupervised ML · NLP and embeddings · ranking and recommendation · A/B testing · causal inference · model evaluation and interpretability

---

## What I bring from research

- **First-principles thinking:** breaking open-ended problems into well-formed questions with the right method for the data-generating process.
- **Measurement and study design:** sampling protocols, data quality standards, bias and missingness at the source — not as afterthoughts.
- **Delivery under real constraints:** scoping work, managing trade-offs, and shipping high-quality outputs on time.
- **Transparent communication:** clear, auditable narratives with explicit assumptions, evidence, and limitations — the standard I held in peer-reviewed work, applied to every project.
- **Cross-functional collaboration:** working across disciplines, mentoring others, and building alignment through clear writing and structured proposals.

---

## Technical depth

<details>
<summary><strong>Bayesian, hierarchical & spatiotemporal modelling</strong></summary>

<div markdown="1">

- Generalised linear models (GLMs) and generalised additive models (GAMs) for nonlinear effects  
- Threshold and segmented regression for decision-point inference  
- Hierarchical and mixed-effects modelling; partial pooling  
- Bayesian inference with uncertainty quantification and propagation; priors as explicit assumptions  
- Spatiotemporal modelling: structured dependence, forecasting logic, species distribution modelling (SDMs)  
- Observation vs process modelling: detection–abundance separation; N-mixture models  
- Integrated Population Models (IPMs)

</div>
</details>

<details>
<summary><strong>LLMs, prompt engineering & agents</strong></summary>

<div markdown="1">

- Prompting for structured outputs; reliability patterns (prompt scaffolds, self-checks, evaluation loops)
- Tool calling and retrieval patterns; schema/contract design for model outputs
- Agent workflows: planning/acting loops, orchestration, retries, human-in-the-loop checkpoints
- LangGraph concepts: state, control flow, tracing/debugging
- Multi-model experimentation: Frontier APIs (OpenAI, Anthropic, Google) and open-source models via HuggingFace
- Multimodal inputs: text, image, and audio processing in LLM pipelines
- RAG: vector embeddings, open-source vector datastores, retrieval pipeline design
- Fine-tuning — Frontier: supervised fine-tuning of closed models for domain-specific tasks
- Fine-tuning — Open-source: QLoRA fine-tuning; training open-source models to match or exceed Frontier performance on specific tasks
- LangChain for LLM application orchestration
- Production deployment patterns: end-to-end productionised LLM systems with agentic capabilities

</div>
</details>

<details>
<summary><strong>Machine learning (classical)</strong></summary>

<div markdown="1">

- Supervised learning: linear/logistic regression, tree-based models, random forests, gradient boosting (incl. XGBoost), SVM, k-NN  
- Unsupervised learning: PCA, clustering (K-Means), anomaly detection  
- scikit-learn Pipelines; hyperparameter tuning; model comparison and baselines  

</div>
</details>

<details>
<summary><strong>Deep learning</strong></summary>

<div markdown="1">

- Neural networks for classification and regression  
- Training fundamentals: loss functions, optimisers, regularisation, monitoring and early stopping  
- TensorFlow / Keras / Pytorch: model definition, training, evaluation
- Fine-tuning and parameter-efficient training: QLoRA for open-source LLMs

</div>
</details>

<details>
<summary><strong>Evaluation, interpretability & reporting</strong></summary>

<div markdown="1">

- Validation design: train/val/test, cross-validation, temporal/blocked splits where appropriate  
- Evaluation discipline: leakage checks, calibration awareness, error analysis and slicing, robustness/stress testing  
- Interpretability: feature importance, partial dependence, SHAP-style global/local explanations  
- Decision-ready reporting: assumptions, limitations, tradeoffs, and clear recommendations  

</div>
</details>

<details>
<summary><strong>Experimentation & causal inference</strong></summary>

<div markdown="1">

- A/B testing fundamentals: hypotheses, metrics, power and effect size  
- Causal inference basics: confounding, selection bias, counterfactual framing, limits of identification  
- Practical decision-making under uncertainty: interpreting results and communicating tradeoffs  

</div>
</details>

<details>
<summary><strong>Data engineering & integration</strong></summary>

<div markdown="1">

- Data ingestion and transformation: structured files, schema discipline, reliable I/O  
- SQL-centric data work: joins across complex relational datasets, analytics transformations  
- API integration patterns: extracting, normalising, and joining external data sources  

</div>
</details>

<details>
<summary><strong>Software engineering & reproducibility</strong></summary>

<div markdown="1">

- Git/GitHub workflows: branching, pull requests, code review, merge discipline  
- Maintainable codebases: modular architecture, clean interfaces, reusable components, pipeline-style structure  
- Quality controls: input validation, assertions, unit tests (pytest patterns), docstrings, type hints where useful  
- Reproducibility: environment management (conda/venv), deterministic runs, versioned artefacts, methods-first documentation  

</div>
</details>

<details>
<summary><strong>NLP, recommenders & text features</strong></summary>

<div markdown="1">

- Text preprocessing and inspection: normalisation, tokenisation, feature auditing  
- Vectorisation: bag-of-words, TF-IDF, and dense embeddings (SBERT, sentence-transformers); semantic search and similarity-based retrieval
- Recommender foundations: similarity metrics, collaborative filtering, constraint-aware framing  

</div>
</details>

<details>
<summary><strong>Cloud (AWS)</strong></summary>

<div markdown="1">

- Foundational understanding of AWS cloud concepts: shared responsibility, high availability, scalability/elasticity, and core tradeoffs  
- Core AWS services: **EC2**, **Lambda**, **S3**, **EBS**, **EFS**, **RDS**, **DynamoDB**  
- Networking & access fundamentals (high level): **VPC**, **subnets**, **security groups**, **NACLs**, **Internet Gateway**, **NAT Gateway**  
- Observability & governance (high level): **CloudWatch**, **CloudTrail**, **AWS Organizations**, **Cost Explorer**, **Budgets**

</div>
</details>


<details>
<summary><strong>Geospatial & remote sensing</strong></summary>

<div markdown="1">

- Raster/vector workflows; spatial joins; geoprocessing pipelines  
- Spatial feature engineering; landscape/canopy metrics  
- Scalable spatial processing  

</div>
</details>

<details>
<summary><strong>Visualisation & lightweight apps</strong></summary>

<div markdown="1">

- Visualisation: matplotlib, seaborn, plotly; ggplot2  
- Lightweight apps: Streamlit (Python), Gradio (Python), Shiny (R)  

</div>
</details>

---

## Education & Training
A detailed, certificate-linked list of formal education and courses is maintained here: **[Education & Training](/datascience/education/)**.

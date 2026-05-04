# LLM Price Predictor

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/llm_price_predictor

## What it is

The flagship project in the LLM Engineering Lab — a real-time autonomous deal-finding system that scans the web for product deals, prices each one using a multi-model ensemble, and pushes a notification when it finds something worth buying. Under the hood it covers the full ML lifecycle: 820k-item Amazon data curation, LLM-powered preprocessing, training and benchmarking across a dozen model families, RAG over 800k documents, serverless cloud deployment, and an autonomous LLM-orchestrated agent that ties it all together with a live Gradio dashboard.

The deliberate point: not whether LLMs can predict prices, but **which approach gives the best accuracy per cost** — answered through rigorous apples-to-apples benchmarking across model families.

## Architecture

Seven-stage pipeline, each stage an independent module:

1. **Data curation (`data_curation_orchestration.py` + `parser.py`)** — loads 820k Amazon products across 8 categories using parallel workers; filters to $0.50–$999.49; strips boilerplate and part numbers; deduplicates; resamples with quadratic weighting to flatten the price-distribution skew (which would otherwise let models cheat by always predicting low prices). Outputs full (~820k) and lite (~23k) splits, both pushed to HuggingFace Hub.
2. **Batch preprocessing (`preprocessing_orchestration.py` + `batch.py`)** — Groq async batch API generates structured summaries (Title / Category / Brand / Description / Details) per item; state persisted to `batches.pkl` so 24-hour jobs survive interruptions.
3. **Fine-tuning preparation (`prompt_prep_fine_tunning.py`)** — tokenises with Llama-3.2-3B tokeniser, truncates to 110-token cap, generates SFT prompt-completion pairs, pushes to HuggingFace Hub.
4. **Modelling and evaluation (`src/pricer/modeling/`)** — all models evaluated on the same test split via shared `Tester` class. QLoRA fine-tuning: 4-bit NF4 quantisation on T4 GPU, LoRA adapters on attention (lite mode) and MLP layers (full mode). Frontier model fine-tuning via OpenAI API.
5. **RAG pipeline (`src/pricer/RAG/`)** — 800k training products encoded with `all-MiniLM-L6-v2` and stored in ChromaDB (~70 min one-time build). Inference retrieves 5 most similar products and passes them as context to GPT-5.1 grounding predictions in real comparable products.
6. **Ensemble + autonomous agents (`src/pricer/agents/`)** — three predictors blended: GPT-5.1+RAG (80%), fine-tuned specialist on Modal (10%), DNN (10%). RAG leads the blend; specialist + DNN dampen outliers. `AutonomousPlanningAgent` gives GPT-5.1 three tools (`scan_the_internet_for_bargains`, `estimate_true_value`, `notify_user_of_deal`) and lets it plan autonomously — the orchestration logic lives in the model, not in code.
7. **Gradio UI (`src/pricer/deployment/price_is_right.py`)** — live dashboard streams agent logs in real time via background thread + queue; displays deals in a clickable dataframe; renders 3D t-SNE scatter of 800k vectorstore embeddings; auto-refreshes every 5 minutes.

## Key engineering decisions

- **`Item` Pydantic model as pipeline contract.** Single dataclass carried through all 7 stages; fields populated progressively (title/price at curation, summary at preprocessing, prompt/completion at fine-tuning prep). Push/pull to HuggingFace Hub by stage.
- **Shared `Tester` class for all models.** Same numeric extraction logic for traditional ML, deep learning, and generative LLMs alike. Without this the comparison would be apples-to-oranges.
- **Quadratic resampling at curation.** Raw Amazon data skews heavily low-price. Without resampling, models game MAE by always predicting cheap. Resampling makes the price distribution more uniform so models actually have to learn from features.
- **LLM preprocessing before fine-tuning.** Raw descriptions are noisy boilerplate; structured LLM summaries fix this once for all downstream models. Fine-tuning on cleaned input is what makes the open-source specialist competitive with frontier models.
- **Resumable async jobs.** Groq batch and OpenAI fine-tuning runs can take 24 hours. Persist-and-poll pattern with state on disk lets jobs survive notebook restarts and network drops.
- **Autonomous planning agent (model decides, not code).** `AutonomousPlanningAgent` has no fixed workflow — it reasons over which tool to call next given the current state. Demonstrates the LLM-as-orchestrator pattern at production scale (vs. the deterministic `PlanningAgent` used by the Gradio backend, which has hardcoded ordering for predictable UI behaviour).
- **Modal serverless deployment for the fine-tuned specialist.** Inference-only model deployed as a serverless endpoint; called by the ensemble at runtime alongside RAG and DNN. Demonstrates production cloud deployment of fine-tuned models.

## Results

**Final ensemble: MAE $29.95 and R² 86.3%** on a held-out test set of 10,000 Amazon products. Ensemble weights: GPT-5.1+RAG (80%), fine-tuned Modal specialist (10%), DNN (10%).

**12 model families benchmarked** (a dozen): four traditional ML baselines (Constant, Linear, Random Forest, XGBoost), 8-layer MLP, 10-layer ResNet (log-space), GPT-4.1-nano (zero-shot), GPT-4.1-nano (fine-tuned), Llama-3.2-3B (base), Llama-3.2-3B (QLoRA fine-tuned), GPT-5.1+RAG, and the final ensemble. Datasets published to HuggingFace Hub: `Alejandrofupi/items_full` (820k) and `Alejandrofupi/items_lite` (23k).

## Stack

Python · OpenAI · Llama-3.2-3B · QLoRA · ChromaDB · `sentence-transformers` · Modal · HuggingFace Hub · Groq batch API · Pushover · Weights & Biases · Gradio · Pydantic

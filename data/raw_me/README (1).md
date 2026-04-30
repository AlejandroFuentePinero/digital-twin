# LLM Engineering Lab

<p align="center">
  <img src="media/llm_engineer.png" alt="LLM Engineering Lab" width="900">
</p>

## Overview

A portfolio of production-grade LLM systems built from scratch — spanning RAG at 800k-document scale, open-source and frontier model fine-tuning, multi-agent orchestration, and serverless cloud deployment. Every project is end-to-end: real data, real evaluation, real infrastructure.

**Skills demonstrated across this repo:**
- **RAG**: vector ingestion, embedding search, retrieval-augmented generation at scale (800k documents)
- **Fine-tuning**: QLoRA fine-tuning of open-source LLMs (Llama 3.2 3B) on Colab and frontier model fine-tuning via the OpenAI API
- **Agents and orchestration**: tool-use agents, autonomous planning loops, multi-agent coordination, real-time deal detection and notification
- **Cloud deployment**: Modal serverless deployment, HuggingFace Hub integration, async batch jobs
- **Multimodal**: vision and voice capabilities across select projects
- **Evaluation**: rigorous benchmarking across a dozen model families on the same held-out test set

Projects escalate in complexity. Earlier ones establish core patterns like structured prompting, retrieval, and tool use. The flagship project (LLM Price Predictor) brings everything together into one end-to-end system: data curation at scale, LLM preprocessing, model training, RAG, ensemble inference, and an autonomous agent that scans for deals, prices them, and notifies the user in real time.

## Skills by project

| Project | Skills |
|---|---|
| LLM Price Predictor | Data curation pipeline, LLM batch preprocessing, QLoRA fine-tuning (Llama 3.2 3B), frontier model fine-tuning (OpenAI API), RAG (ChromaDB + sentence-transformers), multi-model ensemble, agent system design, tool-use agents, autonomous planning loops, serverless deployment (Modal), HuggingFace Hub, async job management, structured outputs (Pydantic), LLM evaluation and benchmarking, Weights & Biases, push notifications (Pushover) |
| Expert Knowledge Worker (RAG Chatbot) | RAG (LangChain + ChromaDB), document chunking, vector embeddings, query rewriting, LLM reranking, hierarchical RAG, retrieval evaluation (MRR, nDCG), LLM-as-judge evaluation, structured outputs, Gradio UI |
| Web Summary Tool | Prompt engineering, web scraping, LLM inference (OpenAI + Ollama), multi-backend integration, persona and tone control |
| Company Brochure Generator | Multi-step LLM chaining, web scraping, structured prompting, streaming generation, Gradio UI, multi-language output |
| Tech Tutor | System prompt design, persona control, multi-backend (OpenAI + Ollama), streaming responses, Gradio UI |
| Multi-Agent Conversation | Multi-agent orchestration, shared state management, prompt-as-contract, role prompting, turn-based agent loops |
| Sales Intake Copilot | Conversational AI, structured output generation, prompt engineering, streaming responses, Gradio UI |
| Flight Booking Agentic Tool | Tool use and function calling, JSON tool schemas, stateful backend (SQLite), multi-step agentic loop, TTS (text-to-speech), image generation, Gradio UI |
| Meeting Minute Generator | Audio transcription (Whisper), LLM summarisation, prompt-as-contract, multimodal (audio + text), structured output |
| Synthetic A/B Dataset Generator | Structured data generation, schema-as-contract prompting, LLM-generated metadata, Gradio UI |
| LLM Code Performance Benchmark | LLM benchmarking, code generation, multi-model and multi-provider evaluation (OpenAI, Anthropic, Ollama, OpenRouter), performance measurement |

## Table of contents
- [LLM Price Predictor](#llm-price-predictor)
- [Expert Knowledge Worker (RAG Chatbot)](#expert-knowledge-worker-rag-chatbot)
- [Web Summary Tool](#web-summary-tool)
- [Company Brochure Generator](#company-brochure-generator)
- [Tech Tutor](#tech-tutor)
- [Multi-Agent Conversation](#multi-agent-conversation)
- [Sales Intake Copilot](#sales-intake-copilot)
- [Flight Booking Agentic Tool](#flight-booking-agentic-tool)
- [Meeting Minute Generator](#meeting-minute-generator)
- [Synthetic A/B Dataset Generator](#synthetic-ab-dataset-generator)
- [LLM Code Performance Benchmark](#llm-code-performance-benchmark)


---

# Projects

## [LLM Price Predictor](./llm_price_predictor/)

<p align="center">
  <img src="media/price_predictor_hero.png" alt="LLM Price Predictor" width="900">
</p>

A system that scans the web for deals in real time, prices each one using a multi-model ensemble, and sends a push notification when it finds something worth buying. Under the hood it covers the full ML lifecycle: 820k-item data curation, LLM-powered preprocessing, training and benchmarking across a dozen model architectures, RAG over 800k documents, serverless cloud deployment, and an autonomous agent that ties it all together in a live Gradio dashboard.

### Business problem

Product pricing at scale is hard. Prices depend on brand, category, material, and dozens of other factors buried in unstructured text. A model that can estimate price from a product description has direct applications in marketplace pricing tools, procurement automation, and catalogue quality checks.

The real question is not whether an LLM can do this, but which approach gives the best accuracy per cost. That requires a rigorous, apples-to-apples comparison across model families.

### What it does

The system is split into seven stages, each with its own module:

- **Data curation (`data_curation_orchestration.py` + `parser.py`)**
  - loads Amazon product data across 8 categories from the McAuley-Lab dataset using parallel workers
  - filters items to a $0.50-$999.49 price range, removes those under 600 characters, and strips part numbers and boilerplate
  - deduplicates by title and full text, then resamples using quadratic weighting to reduce the dominance of low-priced items
  - produces a full dataset (~820k items) and a lite version (~23k items), both pushed to HuggingFace Hub

- **Batch preprocessing (`preprocessing_orchestration.py` + `batch.py`)**
  - submits product descriptions to Groq's async batch API, which handles job submission, polling, and result retrieval
  - generates structured summaries (Title, Category, Brand, Description, Details) using the `Preprocessor` class backed by an LLM
  - saves state to disk (`batches.pkl`) so jobs can be resumed after interruption without data loss
  - pushes summarised items back to HuggingFace Hub

- **Fine-tuning preparation (`prompt_prep_fine_tunning.py`)**
  - tokenises summaries with the Llama-3.2-3B tokeniser and truncates to a 110-token cap
  - generates prompt-completion pairs in SFT format and pushes them to HuggingFace Hub

- **Modelling and evaluation (`src/pricer/modeling/`)**
  - trains and evaluates multiple model families on the same test split, comparing all on MAE, MSE, and R²
  - open-source fine-tuning uses QLoRA: the base model is loaded in 4-bit NF4 quantisation (~2 GB on a T4 GPU), with LoRA adapters trained on attention layers in lite mode and also MLP layers in full mode

- **RAG pipeline (`src/pricer/RAG/`)**
  - `rag_ingest.py` encodes all 800k training products with `sentence-transformers/all-MiniLM-L6-v2` and stores them in a ChromaDB vectorstore (build once, ~70 min)
  - `rag_pipeline.py` retrieves the 5 most similar products for each test item and passes them as context to GPT-5.1, grounding predictions in real comparable products

- **Ensemble (`src/pricer/modeling/ensemble_benchmark.py`)**
  - combines three predictors: GPT-5.1+RAG (80%), a fine-tuned specialist deployed on Modal (10%), and the DNN (10%)
  - the DNN is the same 10-layer residual network from `DNN_benchmark.py`; `modeling/deep_neural_network.py` handles training while `agents/deep_neural_network.py` is the inference-only version used at runtime
  - the RAG model leads the blend while the specialist and DNN act as anchors that dampen outliers

- **Agent system (`src/pricer/agents/`)**
  - production-ready wrappers around each model: `FrontierAgent` (GPT-5.1+RAG), `NeuralNetworkAgent` (DNN), `SpecialistAgent` (Modal), `EnsembleAgent` (combines all three)
  - `EnsembleAgent` first rewrites the product description with a lightweight local LLM via `agents/preprocessor.py` (litellm + Ollama by default) before passing the cleaned text to each pricing model — this mirrors the LLM preprocessing done at training time and keeps the input distribution consistent at inference
  - `AutonomousPlanningAgent` is an LLM-driven orchestrator: GPT-5.1 receives three tools (`scan_the_internet_for_bargains`, `estimate_true_value`, `notify_user_of_deal`) and decides autonomously which deals to evaluate, runs the ensemble on each, picks the best opportunity, and triggers a notification. The orchestration logic lives in the model, not in code
  - `DealAgentFramework` is the persistent backend used by the Gradio UI: it wraps `PlanningAgent`, maintains a `memory.json` of previously surfaced deals across runs, and exposes a `get_plot_data()` method that fetches embeddings from ChromaDB and reduces them to 3D with t-SNE for visualisation
  - `ScannerAgent` scrapes RSS deal feeds, filters out previously seen URLs, and uses GPT structured outputs to select the 5 deals with the clearest prices and best descriptions
  - `MessagingAgent` uses Claude to write the notification message and delivers it via the Pushover API
  - run the full autonomous workflow from the terminal: `uv run python llm_price_predictor/src/pricer/agents/run_agentic_workflow.py`
  - `agents/items.py` is a lightweight `Item` for inference only; the full version with fine-tuning fields lives in `data_prep/items.py`

<p align="center">
  <img src="media/price_predictor_agent_hierarchy.svg" alt="Agent hierarchy diagram" width="900">
</p>

- **Gradio UI (`src/pricer/deployment/price_is_right.py`)**
  - a live dashboard that runs the deal-finding agent on load and refreshes every 5 minutes
  - streams agent logs in real time to the UI using a background thread and queue, with ANSI colours converted to HTML via `log_utils.py`
  - displays found deals in a dataframe; clicking a row manually re-sends the push notification for that deal
  - renders a 3D scatter plot of the vectorstore embeddings (coloured by product category) using t-SNE dimensionality reduction
  - uses `PlanningAgent` (deterministic hardcoded pipeline) rather than `AutonomousPlanningAgent` (LLM-driven loop); the terminal workflow and the UI therefore behave slightly differently in how they orchestrate the scan
  - requires: ChromaDB vectorstore already ingested, `deep_neural_network.pth` weights present, Modal deployment live, and Pushover credentials set
  - run with: `uv run python llm_price_predictor/src/pricer/deployment/price_is_right.py`

<p align="center">
  <img src="media/pricer_gradio_demo.png" alt="The Price is Right - Gradio UI" width="900">
</p>

### Models benchmarked

<p align="center">
  <img src="media/price_predictor_comp_final.png" alt="LLM Price Predictor — model comparison" width="900">
</p>

### Ensemble model result

<p align="center">
  <img src="media/ensemble_pricer_res.png" alt="Ensemble model result" width="900">
</p>

The final ensemble achieves a mean absolute error of **$29.95** and **R² of 86.3%** on a held-out test set of 10,000 Amazon products.

| Model | Type |
|---|---|
| Constant / Linear / Random Forest / XGBoost | Traditional ML baselines |
| Neural Network (8-layer MLP) | Deep learning |
| Deep Neural Network (10-layer ResNet, log-space) | Deep learning |
| GPT-4.1 Nano (zero-shot) | Frontier LLM, pre-trained |
| GPT-4.1 Nano (fine-tuned) | Frontier LLM, fine-tuned |
| Llama-3.2-3B (base, no fine-tuning) | Open-source LLM, pre-trained |
| Llama-3.2-3B (fine-tuned) | Open-source LLM, fine-tuned |
| GPT-5.1 + RAG | Frontier LLM with retrieval augmentation |
| Ensemble (GPT-5.1+RAG + fine-tuned specialist + DNN) | Multi-model ensemble |

### Core data model: `Item`

`Item` (`src/pricer/data_prep/items.py`) is the Pydantic model that carries a product through every stage of the pipeline. Fields are populated progressively as the item moves from raw ingestion through preprocessing, prompt generation, and fine-tuning.

| Field | Type | Populated at | Purpose |
|---|---|---|---|
| `title` | `str` | Curation | Product title |
| `category` | `str` | Curation | Amazon product category |
| `price` | `float` | Curation | Ground truth label |
| `full` | `str` (opt) | Curation | Raw concatenated product text (pre-summary) |
| `weight` | `float` (opt) | Curation | Sampling weight (quadratic, used for resampling) |
| `summary` | `str` (opt) | Preprocessing | LLM-generated structured summary (Title / Category / Brand / Description / Details) |
| `prompt` | `str` (opt) | Fine-tuning prep | Full prompt: `"What does this cost to the nearest dollar?\n\n{summary}\n\nPrice is $"` |
| `completion` | `str` (opt) | Fine-tuning prep | Target completion: `"{price}.00"` (rounded for train/val, exact for test) |
| `id` | `int` (opt) | Preprocessing | Stable ID for matching batch API results back to items |

Key methods:

- **`make_prompts(tokenizer, max_tokens, do_round)`**: tokenises the summary, truncates to `max_tokens` if needed, and writes `prompt` and `completion`. Use `do_round=True` for train/val (rounded price) and `False` for test (exact price).
- **`test_prompt() -> str`**: strips the completion from the prompt, returning only the question half for inference.
- **`push_to_hub / from_hub`**: serialises and deserialises full `Item` lists to/from HuggingFace Hub across train, validation, and test splits.
- **`push_prompts_to_hub`**: pushes only the `{"prompt", "completion"}` pairs needed for SFT training.

### Design notes

- **Stage-based orchestration**: each pipeline stage is an independent module that can be re-run or swapped without touching the others. This matters when iterating on a single layer, such as testing a different prompt format for fine-tuning.

- **LLM preprocessing**: raw Amazon descriptions are noisy, full of boilerplate and HTML artefacts. Running an LLM batch step to produce clean structured summaries before any model sees the data is what makes fine-tuning effective and the benchmark comparison fair. All models consume the same cleaned input.

- **Weighted resampling**: the raw dataset skews heavily toward low-priced items. Quadratic resampling at curation time makes the price distribution more uniform, which prevents models from gaming MAE by always predicting a low price.

- **Shared evaluation**: all models go through the same `Tester` class (`src/pricer/agents/evaluator.py`), which handles numeric extraction from raw string outputs. This keeps the comparison fair across traditional models, deep learning, and generative LLMs alike.

- **Resumable async jobs**: Groq batch processing and OpenAI fine-tuning can run for up to 24 hours. Both use a persist-and-poll pattern, saving state to disk so jobs survive notebook restarts and network interruptions.

### Pipeline configuration (current defaults)

- **Preprocessing model**: Groq batch API (LLM summarisation)
- **Vectoriser**: `HashingVectorizer` (5,000 binary features) for NN / DNN models
- **Fine-tuning base model**: `meta-llama/Llama-3.2-3B` (QLoRA: 4-bit NF4, LoRA-R 32 lite / 256 full, attention layers only in lite mode)
- **Frontier fine-tuning model**: `gpt-4.1-nano-2025-04-14`
- **Token cutoff (prompts)**: 110 tokens
- **Dataset splits**: 800k / 10k / 10k (full), 20k / 1k / 1k (lite)
- **Evaluation sample size**: 200 test items per model run

### Run locally

Modelling and evaluation scripts run locally from the project root. Data curation, batch preprocessing, and fine-tuning require credentials for HuggingFace, Groq, and OpenAI. The ensemble and agentic workflow additionally require `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, and `PUSHOVER_USER` / `PUSHOVER_TOKEN`.

1. Set your environment variables in a `.env` file: `HF_TOKEN`, `OPENAI_API_KEY`, `GROQ_API_KEY`
2. Run any benchmark:
   - Neural network: `uv run python llm_price_predictor/src/pricer/modeling/NN_benchmark.py`
   - Deep neural network: `uv run python llm_price_predictor/src/pricer/modeling/DNN_benchmark.py`
   - Frontier LLM (zero-shot): `uv run python llm_price_predictor/src/pricer/modeling/LLM_pretuned_benchmark.py`
   - Llama base model (local, Apple Silicon): `uv run python llm_price_predictor/src/pricer/modeling/basemodel_llama_eval_benchmark_local.py`
   - Llama fine-tuned model (local, Apple Silicon): `uv run python llm_price_predictor/src/pricer/modeling/llama_finetunning_eval_local.py`
   - GPT-5.1 + RAG (requires vectorstore built first): `uv run python llm_price_predictor/src/pricer/modeling/openai_gpt5_1_rag_benchmark.py`
   - Ensemble (requires vectorstore + DNN weights + Modal deployment): `uv run python llm_price_predictor/src/pricer/modeling/ensemble_benchmark.py`
   - Autonomous deal-finding agent (requires all of the above + Pushover credentials): `uv run python llm_price_predictor/src/pricer/agents/run_agentic_workflow.py`
   - Gradio UI (requires vectorstore + DNN weights + Modal deployment + Pushover credentials): `uv run python llm_price_predictor/src/pricer/deployment/price_is_right.py`
3. Llama benchmarks and fine-tuning that require a CUDA GPU run in Google Colab (Runtime → T4 GPU). These scripts load from the `items_prompts_full` / `items_prompts_lite` HuggingFace datasets (prompt-formatted, distinct from `items_full` / `items_lite` used by other models):
   - Llama base-model evaluation: `llm_price_predictor/src/pricer/modeling/basemodel_llama_eval_benchmark_colab.py`
   - Llama QLoRA fine-tuning: `llm_price_predictor/src/pricer/modeling/llama_finetunning_training_colab.py`
   - Llama fine-tuned model evaluation: `llm_price_predictor/src/pricer/modeling/llama_finetunning_eval_colab.py`
     - Requires `HF_TOKEN` and `WANDB_API_KEY` in Colab Secrets (Tools → Secrets)
     - Logs training metrics to Weights & Biases; optionally pushes checkpoints to HuggingFace Hub
     - Uses 4-bit NF4 quantisation by default; `LITE_MODE=True` runs a single epoch on the lite dataset for quick iteration

---

## [Expert Knowledge Worker (RAG Chatbot)](./RAG_expert_knowledge_worker/)

<p align="center">
  <img src="media/rag_chatbot.png" alt="Insurellm Expert Assistant" width="900">
</p>

A lightweight Retrieval-Augmented Generation (RAG) assistant for answering questions about a company knowledge base (Insurellm). It combines a document-ingestion pipeline, a vector database, a Gradio chat UI that shows both the assistant response and the retrieved source context side-by-side for transparency, and an evaluation dashboard that measures retrieval and answer quality against a labelled test set.

### Business problem

Internal knowledge is often spread across Markdown docs, notes, and operational writeups. Team members need quick answers, but manually searching across files is slow and inconsistent. A plain chatbot is also risky because it can answer without grounding in the actual company documentation.

This project addresses that by retrieving relevant knowledge-base chunks first, then answering with the LLM using that retrieved context.

### What it does

The project is split into two core workflows:

- **Ingestion (`src/implementation/ingest.py`)**
  - loads Markdown files from a `knowledge-base/` directory (grouped by subfolders)
  - tags each document with metadata (including `doc_type`)
  - chunks documents using a recursive text splitter
  - creates embeddings and stores them in a persistent Chroma vector database (`vector_db/`)
  - rebuilds the collection when re-ingesting

- **Question answering (`src/implementation/answer.py` + `app.py`)**
  - retrieves relevant chunks from the vector DB for a user question
  - combines prior user messages with the current question to improve retrieval context
  - injects retrieved context into a system prompt
  - generates a grounded answer with a chat model
  - returns both:
    - the assistant answer
    - the retrieved source chunks (displayed in the UI)

- **Gradio UI (`app.py`)**
  - chat interface for user questions
  - side panel showing retrieved context and source metadata for inspection
  - simple conversational loop with message history

### Notes on the design (why it's structured this way)

This is a compact but practical RAG pattern for internal assistants:

- **Separate ingestion from answering**
  - document parsing / chunking / embedding happens once (or on refresh)
  - chat-time requests only perform retrieval + generation, which keeps the UI responsive

- **Grounded answers with visible evidence**
  - the assistant answer is shown alongside the retrieved context
  - this makes debugging and trust assessment easier than a "black-box" chat response

- **Conversation-aware retrieval**
  - retrieval uses the current question plus prior user turns, which helps when users ask follow-up questions with ellipsis (e.g., "what about pricing?")

- **Prompt-as-contract**
  - the system prompt explicitly frames the assistant as an Insurellm representative and instructs it to use context when relevant and admit uncertainty when needed

### Retrieval / ingestion configuration (current defaults)

- **Chat model**: `gpt-4.1-nano`
- **Embedding model**: `text-embedding-3-large`
- **Vector store**: Chroma (persistent local directory)
- **Retrieval depth**: `k = 10`
- **Chunking**: `chunk_size=500`, `chunk_overlap=200`

### Interface

Core answering function:

`answer_question(question: str, history: list[dict] = []) -> tuple[str, list[Document]]`

- `question`: latest user question
- `history`: prior conversation turns in message-dict format (`[{role, content}, ...]`)
- returns:
  - `answer` (LLM response string)
  - `docs` (retrieved LangChain `Document` objects)

UI chat callback (Gradio):

`chat(history) -> (history, formatted_context_html)`

- appends the assistant response to the chat history
- formats retrieved documents into a "Relevant Context" panel with sources

### Expected project structure (conceptual)

- `app.py` — Gradio UI entry point
- `src/implementation/answer.py` — retrieval + answer generation
- `src/implementation/ingest.py` — ingestion and vector DB build
- `knowledge-base/` — Markdown source documents (subfolders by category)
- `knowledge-base/summaries/` — LLM-generated category summaries for hierarchical RAG (generated at ingest time)
- `vector_db/` — persisted Chroma database (generated)

### Evaluation system

A standalone evaluation suite (`evaluator.py` + `src/evaluation/`) measures both retrieval and answer quality against a labelled test set (`tests.jsonl`).

**Retrieval evaluation** — for each test question, the system retrieves the top-k chunks and computes:
- **MRR** (Mean Reciprocal Rank): rank position of the first chunk containing each expected keyword
- **nDCG** (Normalized Discounted Cumulative Gain): position-weighted keyword coverage across the result list
- **Keyword coverage**: percentage of expected keywords found anywhere in the retrieved results

**Answer evaluation** — the generated answer is compared against a reference answer by an LLM judge (`gpt-4.1-nano`) using structured outputs, scoring three dimensions on a 1–5 scale:
- **Accuracy**: factual correctness relative to the reference answer
- **Completeness**: coverage of all key information from the reference answer
- **Relevance**: how directly the answer addresses the question without unnecessary additions

Results are displayed in a Gradio dashboard (`evaluator.py`) with colour-coded metrics (green / amber / red) and a per-category bar chart. A CLI mode (`eval.py <test_row_number>`) is also available for inspecting individual test cases.

<img src="media/rag_test.png" alt="RAG Evaluation Dashboard" width="900">

### Run locally

1. Create and activate your environment
2. Install dependencies (LangChain, Chroma, Gradio, OpenAI, dotenv, etc.)
3. Set environment variables (at minimum `OPENAI_API_KEY`)
4. Add your company Markdown files under `knowledge-base/`
5. Build the vector store:
   - `uv run python src/implementation/ingest.py`
6. Launch the chat UI:
   - `uv run python app.py`
7. Launch the evaluation dashboard (optional):
   - `uv run python evaluator.py`

### Demo app (Gradio)

A lightweight Gradio interface is included to demonstrate the full RAG loop (chat → retrieve → answer + visible context). It is intended as a local demo, but the architecture maps cleanly to internal support / knowledge-assistant use cases.

### Optimised RAG pipeline (`optimised_ingest.py` + `optimised_answer.py`)

A drop-in replacement for the LangChain baseline that removes framework abstractions and improves both ingestion quality and retrieval precision. No LangChain dependency — uses the OpenAI SDK, ChromaDB, and LiteLLM directly.

**Ingestion (`optimised_ingest.py`)**

Instead of a fixed-size recursive character splitter, an LLM reads each document and decides how to chunk it. Each chunk is returned as a structured object with three fields:

- **`headline`**: a short label optimised to match likely query phrasing
- **`summary`**: a few sentences synthesising what the chunk answers
- **`original_text`**: the verbatim source passage

All three fields are concatenated and embedded together, so each vector encodes both the dense original content and the LLM-generated surface forms most likely to be retrieved. Documents are processed in parallel using `multiprocessing.Pool` for throughput.

The ingestion pipeline also implements **hierarchical RAG** through a summary generation step that runs before chunking. For each subfolder in `knowledge-base/`, an LLM reads all documents in that category and produces a single aggregated `summary_{category}.md` file saved to `knowledge-base/summaries/`. These summaries are designed to answer holistic questions — totals, counts, averages, and rankings — that are hard to answer from individual fine-grained chunks alone. Summary files are stored as single, unsplit documents in the same ChromaDB collection as regular chunks, so they surface automatically via semantic search when a query requires cross-document aggregation. No changes to the retrieval pipeline are needed: the reranker naturally promotes summaries for holistic queries and demotes them for specific fact lookups.

**Retrieval and answering (`optimised_answer.py`)**

The baseline does a single vector lookup on the raw user question. The optimised pipeline adds four stages before the final answer:

1. **Query rewriting** — the user's question is rewritten into a tighter KB query, stripping conversational noise and sharpening retrieval intent
2. **Chunk merging** — results from the original and rewritten query (`RETRIEVAL_K = 20` each) are deduplicated into a single pool
3. **LLM reranking** — a dedicated reranker call receives the merged pool and returns a `RankOrder` structured output, re-ordering chunks by relevance before the top `FINAL_K = 10` are passed to the answer model

Retry logic via `tenacity` wraps all LLM calls to handle rate limits gracefully.

To switch to the optimised pipeline, `app.py` only requires a one-line import change — everything else (Gradio UI, chat loop, context display) works identically:

```python
# LangChain baseline
from src.implementation.answer import answer_question

# Optimised pipeline
from src.implementation.optimised_answer import answer_question
```

The same applies to `src/evaluation/eval.py`: only the module name changes, the imported functions stay the same:

```python
# LangChain baseline
from src.implementation.answer import answer_question, fetch_context

# Optimised pipeline
from src.implementation.optimised_answer import answer_question, fetch_context
```

---

## [Web Summary Tool](./ai_web_summary_tool/)

<p align="center">
  <img src="media/web_summary.png" alt="Web summary" width="900">
</p>

A small, deployable Python utility that turns a webpage URL into a concise Markdown summary using an LLM. It’s designed to be embedded into internal workflows where people need quick, repeatable briefs from unstructured web content.

### Business problem

Stakeholders often need to extract decision-relevant information from long webpages (announcements, reports, research posts). Manual summarisation is slow, inconsistent, and doesn’t scale across many sources.

### What it does

Given a URL, `web_summary_tool(...)`:
- fetches and extracts the readable text from the webpage
- applies a safety cap (`max_chars`) to prevent oversized prompts
- generates a short summary in Markdown via a chat model
- can run via either a hosted API (OpenAI) or a local open-source model (Ollama)
- either returns the summary text or renders it (controlled by `show`)

### Tone / “personality” control

The tool accepts a `chat_personality` parameter to adapt tone and framing to the audience. This is useful when the same underlying content needs to be summarised differently depending on context (e.g., a terse executive brief vs. a more detailed analyst-style summary). The output remains Markdown so it can drop cleanly into docs, notes, or downstream pipelines.

### Interface

`web_summary_tool(url, chat_personality="…", openai_model="…", ollama_model="…", max_chars=25000, show=True, run_open_ai=True, run_ollama=True)`

- `url`: webpage to summarise  
- `openai_model`: hosted chat model used when `run_open_ai=True`  
- `ollama_model`: local model used when `run_ollama=True`  
- `max_chars`: crude guardrail to limit prompt size  
- `show`: if `True`, displays Markdown; if `False`, returns results as strings  
- `run_open_ai`: enable OpenAI backend (requires `OPENAI_API_KEY`)  
- `run_ollama`: enable Ollama backend (requires Ollama installed and running locally)

---

## [Company Brochure Generator](./company_sales_brochure_generator/)

<p align="center">
  <img src="media/brochure_gen.png" alt="Brochure generator" width="900">
</p>

A reusable Python utility that turns a company website into a short, readable Markdown brochure using an LLM. It’s designed for fast prospecting: generating a consistent “who they are / what they do / why they matter” brief for customers, investors, or recruits — with Markdown output that drops cleanly into docs, notes, CRMs, or downstream workflows.

### Business problem

When evaluating companies (for sales, investing, partnerships, or job applications), the relevant information is spread across multiple pages (About, Products, Careers, Customers). Manually collecting and synthesising this is slow, noisy, and inconsistent — especially when you need to do it repeatedly across many companies.

### What it does

Given a company name and homepage URL, `brochure_generator(...)`:
- collects candidate links from the homepage
- uses a chat model to select a small set of brochure-relevant pages (e.g., About, Products, Careers)
- fetches the text content for the homepage + selected pages
- generates a short brochure in Markdown (no code blocks) covering:
  - what the company does and who it serves
  - products / services and key differentiators (if present)
  - culture and hiring signals (if present)
- optionally translates the brochure into a target language (preserving Markdown structure)
- returns the final Markdown string (optionally streaming it during generation in interactive environments)

### Notes on the design (why it’s structured this way)

This project is a minimal “agentic” workflow: instead of a single giant prompt, it chains multiple LLM calls with a clear intermediate artefact.

- **Step 1: page selection (planning / routing)**  
  The model first decides which pages are worth reading for a brochure (About, Products, Careers, Customers). This reduces noise versus scraping everything.

- **Step 2: content synthesis (generation)**  
  A second call writes the brochure using the retrieved page text as evidence, producing a consistent output format in Markdown.

This two-stage pattern (select → generate) generalises well beyond brochures, for example:
- marketing copy generation from a website + product pages
- investor-style briefs from public company pages
- recruitment briefs from About + Careers pages
- tutorials / internal docs generated from specs + docs pages

### Interface

`brochure_generator(company_name, url, model="gpt-4.1-mini", max_pages=6, translate=False, language="Spanish")`

- `company_name`: label used to frame the brochure narrative  
- `url`: company homepage to crawl  
- `model`: chat model used for both link selection and brochure generation  
- `max_pages`: maximum number of “relevant” pages to fetch in addition to the landing page  
- `translate`: if `True`, returns the brochure in the requested language  
- `language`: target language for translation (e.g., `"Spanish"`, `"French"`)

### Demo app (Gradio)

A lightweight Gradio UI is included to demonstrate how the utility can be embedded in an interactive tool (local demo; not production hosted). It calls `brochure_generator(...)` under the hood and renders the brochure as Markdown.

- entry point: `./company_sales_brochure_generator/src/app.py`
- run locally:
  - ensure `OPENAI_API_KEY` is set (via `.env` or environment)
  - start the app: `uv run python company_sales_brochure_generator/src/app.py`


---

## [Tech Tutor](./tech_tutor/)

<p align="center">
  <img src="media/tech_tutor.png" alt="Tech AI tutor" width="900">
</p>

A small, reusable Python utility that answers questions about data work (data engineering, data science, machine learning, and general software concepts) and explains code in clear Markdown using an LLM. It’s designed for fast learning loops: ask a question, paste a snippet, get a memorable explanation you can drop into notes, docs, or study material.

### Business problem

People working in data roles constantly encounter unfamiliar concepts, jargon, and code patterns (model behaviour, pipeline logic, SQL idioms, ML tooling). Searching the web often yields fragmented answers, and generic AI responses can be either overly technical or overly “tutorial-ish”. What’s missing is a consistent, high-signal tutor that can explain *precisely* and *memorably* on demand.

### What it does

Given a question (and optionally a code snippet), `tech_tutor(...)`:
- produces a concise, high-signal explanation aimed at a competent coder new to the specific topic
- uses a single movie-based analogy thread (configured via `favourite_movie`) to make the concept stick without overshooting into fan-fiction
- supports both concept explanations and “what does this code do?” walkthroughs (plus practical gotchas)
- returns Markdown suitable for pasting into notes / docs, and can optionally render it when running interactively
- can run via either a hosted API (OpenAI) or a local open-source model (Ollama)

### Tone / “storytelling” control

The tutor is deliberately designed to be more memorable than a standard technical answer. The analogy is not a decorative add-on: it’s used as the backbone of the explanation, with short technical “translations” to keep the answer rigorous. This makes it useful for learning, interview prep, and quickly internalising new patterns.

### Interface

`tech_tutor(question, code=None, favourite_movie="…", openai_model="…", ollama_model="…", temperature=0.7, show=True, run_open_ai=True, run_ollama=True, ollama_base_url="http://localhost:11434/v1")`

- `question`: the concept or code question to answer  
- `code`: optional code snippet to explain  
- `favourite_movie`: the story universe used for the analogy thread  
- `openai_model`: hosted chat model used when `run_open_ai=True`  
- `ollama_model`: local model used when `run_ollama=True`  
- `temperature`: creativity level (higher = more playful analogies)  
- `show`: if `True`, renders Markdown in interactive environments; otherwise returns strings  
- `run_open_ai`: enable OpenAI backend (requires `OPENAI_API_KEY`)  
- `run_ollama`: enable Ollama backend (requires Ollama installed and running locally)  
- `ollama_base_url`: OpenAI-compatible local endpoint for Ollama

### Demo app (Gradio)

A lightweight Gradio UI is included to demonstrate the tutor in an interactive setting (local demo; not production hosted). It supports streaming responses, switching between OpenAI and Ollama backends, and optionally pasting code alongside the question.

- entry point: `./tech_tutor/src/app.py`
- run locally:
  - ensure `OPENAI_API_KEY` is set (via `.env` or environment)
  - start the app: `uv run python -m tech_tutor.src.app`

---

## [Multi-Agent Conversation](./agentic_conversation/)

<p align="center">
  <img src="media/agent_conversation.png" alt="Multi-Agent Conversation" width="900">
</p>

A small Python project that orchestrates a turn-based, three-agent “review panel” conversation. Each agent plays a business-relevant role — a skeptical Staff Data Scientist, a pragmatic Product Manager, and a Tech Lead who synthesizes the debate into a shippable plan. It’s designed as a learning lab for multi-agent prompting, shared state management, and prompt-as-contract discipline.

### Business problem

Multi-agent workflows often fail in subtle ways: stale context, role drift, duplicated state updates, and inconsistent turn-taking. These failures are easy to miss in demos but break reliability in real use cases such as decision reviews, red/blue teaming, and structured critique → synthesis pipelines.

### What it does

Given a topic, `agentic_conversation(...)`:
- initializes a shared conversation transcript (the single source of truth)
- runs a turn-based loop where agents respond in sequence using role-specific system prompts
- appends each response back into the shared state so subsequent turns condition on the evolving dialogue
- produces a transcript that can be inspected, logged, or adapted into downstream workflows (e.g., “debate → decision memo”)

### Notes on the design (why it’s structured this way)

This project is intentionally small, but it surfaces core multi-agent engineering pitfalls:
- **State is the source of truth**: each turn must be generated from the latest transcript, not a frozen prompt string.
- **Prompt contracts**: each agent is constrained to a stable role, tone, and response length to reduce drift.
- **Turn-taking discipline**: one agent speaks at a time, and state updates happen exactly once per turn to avoid duplication.
- **Synthesis as a deliverable**: the Tech Lead role is explicitly responsible for converging toward actionable next steps.

### Interface

`agentic_conversation(topic: str, conversation_length: int = 5)`

- `topic`: discussion topic to evaluate in a business context  
- `conversation_length`: number of full rounds (Alex → Blake → Charlie) to run  

### Code

Entry point script: `./agentic_conversation/src/multi-agent-chat.py`

---

## [Sales Intake Copilot](./sales_chatbot_assistant/)

<p align="center">
  <img src="media/sales_intake.png" alt="Sales Intake Copilot" width="900">
</p>

A lightweight B2B “sales intake” chatbot that qualifies a lead in a few turns and produces an internal handoff note for a human sales rep. It’s designed to demonstrate a business-realistic pattern: conversational intake on the front-end, structured operational artefacts on the back-end.

### Business problem

In many B2B workflows, inbound leads arrive with incomplete context. Sales teams waste time in back-and-forth messages to extract basic qualification details (use case, timing, size, decision ownership), and handoffs between marketing → SDR → AE are often inconsistent or missing key information.

### What it does

Given a user message, the chatbot:
- responds naturally to the user and asks a small number of targeted qualifying questions
- captures key lead attributes (use case, industry, company size, timeline, budget, authority)
- produces an internal “handoff note” in a consistent template so a human rep can take over quickly
- avoids inventing details

### Interface

`sales_assistant_stream(message, history)`

- `message`: the latest user message  
- `history`: prior turns in Gradio “messages” format (`[{role, content}, ...]`)  
- `model`: chat model used to generate the reply + handoff note (currently `gpt-4.1-mini`)

### Demo app (Gradio)

A lightweight Gradio UI is included to demonstrate the intake flow in an interactive setting (local demo; not production hosted). It calls `sales_assistant_stream(...)` under the hood.

- entry point: `./sales_chatbot_assistant/src/app.py`
- run locally:
  - ensure `OPENAI_API_KEY` is set (via `.env`)
  - start the app: `uv run python -m sales_chatbot_assistant.src.app`

---

## [Flight Booking Agentic Tool](./price_ticket_agentic_tool/)

<p align="center">
  <img src="media/flight_agent.png" alt="Flight Booking Agentic Tool" width="900">
</p>

A small Gradio app that demonstrates tool-calling with a real stateful backend: the assistant can quote return ticket prices from SQLite and create mock bookings with booking IDs and departure times. It’s designed as a minimal “agentic” pattern: structured tool schemas + a tool router + a multi-step loop that keeps the model and tool outputs in sync.

### Business problem

In many customer support or sales workflows, users ask simple, repeatable questions (“what’s the price to Tokyo?”) and then want to take an action (“book it”) without a human operator. Pure chat responses are not enough: you need deterministic retrieval and a reliable way to write state (even if mocked) while keeping the conversational experience intact.

### What it does

Given a chat history, the agent:
- calls `get_ticket_price` to retrieve prices from a SQLite `prices` table
- asks for confirmation before booking, then calls `book_ticket` to insert a new row into a `bookings` table (autoincrement booking IDs)
- returns a one-sentence reply to the user, plus:
  - an autoplay TTS audio version of the reply
  - an optional destination image generated from the first city referenced in tool calls

### Notes on the design (why it’s structured this way)

This project is intentionally small, but it captures the core mechanics you need for reliable tool use:
- **Prompt-as-contract**: the system prompt enforces one-sentence answers and “confirm before booking”.
- **Tool schemas as interfaces**: JSON schemas constrain the model’s tool-call arguments (`destination_city`, optional `depart_at`).
- **Tool-call loop discipline**: the app executes tool calls, appends both the tool request and tool results back into `messages`, and re-calls the model until it returns a final response (supports multi-step tool usage).
- **Stateful backend**: SQLite provides deterministic retrieval and a persistent booking record (mock but real state).

### Interface

`booking_agent(history) -> (history, voice_audio_bytes, image)`

- `history`: Gradio “messages” format (`[{role, content}, ...]`)
- `voice_audio_bytes`: TTS audio bytes for autoplay
- `image`: PIL image for the destination (optional)

### Demo app (Gradio)

![Flight booking agent — Demo](media/flight_booking_demo.gif)

A lightweight Gradio Blocks UI is included to demonstrate the full loop (chat → tool call → response), with audio + image outputs.

- entry point: `./price_ticket_agentic_tool/src/flight_booking_agent.py`
- run locally:
  - ensure `OPENAI_API_KEY` is set (via `.env` or environment)
  - start the app: `uv run python price_ticket_agentic_tool/src/flight_booking_agent.py`

---

## [Meeting Minute Generator](./meeting_minute_audio/)

<p align="center">
  <img src="media/meeting_minute.png" alt="Meeting minute generator" width="900">
</p>

A Python utility that turns meeting audio into structured Markdown minutes using an LLM. It’s designed for workflows where meetings happen frequently, recordings exist, and teams need consistent documentation without relying on manual note-taking.

### Business problem

Minutes are a core operational artefact: they capture decisions, context, and action items. When they are missing or inconsistent, teams lose accountability, repeat discussions, and waste time rebuilding context for stakeholders who weren’t in the room.

### What it does

Given an audio recording, `meeting_minute_generator(...)`:
- transcribes the meeting audio
- generates minutes in Markdown with a fixed, contract-driven structure:
  - summary (attendees/date/location if stated)
  - key discussion points (controlled granularity)
  - takeaways
  - action items with owners and due dates (if stated)
- avoids inventing details: missing information is explicitly marked as *Not specified*
- saves the exact transcript used for each run for traceability and debugging
- renders Markdown in notebooks or prints clean output in terminal runs

### Notes on the design (why it’s structured this way)

This tool prioritises reliability over creativity:
- **Prompt-as-contract** to enforce consistent format and detail level
- **Low-temperature generation** to reduce run-to-run variability
- **Faithfulness guardrails** to avoid invented metadata or action items
- **Transcript persistence** to diagnose whether issues are transcription- or summarisation-driven

---

## [Synthetic A/B Dataset Generator](./synthetic_data_generator/)

<p align="center">
  <img src="media/data_generator.png" alt="Synthetic A/B Dataset Generator" width="900">
</p>

A lightweight Gradio app that generates a compact synthetic A/B conversion dataset (CSV) plus a Markdown “dataset card” using an LLM. It’s designed for quick demo datasets: small, usable tables with a clear schema, controlled treatment effect, and immediately readable documentation. Ideal for model testing and benchmarking.

### Business problem

Teams often need realistic A/B-style datasets for prototyping dashboards, testing analytics pipelines, teaching experimentation concepts, or building demos. Real production data is sensitive, slow to access, and rarely shareable. Synthetic data solves this — but only if it is structured, consistent, and documented enough to be usable.

### What it does

Given a set of knobs, the generator:
- uses a schema-as-contract to force a fixed set of columns and allowed values
- generates a CSV dataset with a control and treatment variant and a binary conversion outcome
- produces a Markdown dataset card summarising the dataset (shape, column dictionary, allocation and conversion rates, observed lift)
- saves both artefacts to disk (`.csv` and `_metadata.md`) and renders the dataset card in the UI

### Demo app (Gradio)

<p align="center">
  <img src="media/ab_data_demo.png" alt="Synthetic A/B Dataset Generator Demo" width="900">
</p>

- entry point: `./synthetic_data_generator/src/ab_data_generator.py`
- run locally:
  - ensure `OPENAI_API_KEY` is set (via `.env` or environment)
  - start the app: `uv run python synthetic_data_generator/src/ab_data_generator.py`

---

## [LLM Code Performance Benchmark](./llm_code_performance_benchmark/)

<p align="center">
  <img src="media/code_performance.png" alt="LLM Code Performance Benchmark" width="900">
</p>

A Python benchmark that compares LLMs on a practical “speedup” task: translating a Python workload into high-performance C++ and measuring the runtime improvement. It supports both hosted models (OpenAI / Anthropic) and open-source models (via local Ollama or OpenRouter), and saves each model’s generated C++ as an artefact for inspection and reproducibility.

### Business problem

Many teams have Python code that is correct but too slow in production or in critical research workflows. Rewriting hot paths in C++ is a classic solution, but it is time-consuming and requires specialist expertise.

LLMs can generate C++ ports quickly, but performance and correctness vary by model and by task. This creates a model-selection problem: for a given workload, which model produces the fastest correct implementation — and how often does it fail?

### What it does

Given a Python benchmark script, the tool:
- runs the Python code as the baseline and captures:
  - the computed `result`
  - the measured `execution_time`
- asks each target LLM to port the Python into C++ with a performance-first prompt contract
- writes each model output to `{model}_main.cpp` (safe filename) as a persistent artefact
- compiles and executes the generated binary
- parses the C++ program output to extract:
  - `Result: ...`
  - `Execution Time: ... seconds`
- reports speedup as `python_runtime / cpp_runtime` per model

It also distinguishes failure modes during evaluation:
- **LLM compile error**: model produced invalid / non-compilable C++
- **LLM runtime error**: binary compiled but crashed / exited non-zero

This is useful when comparing models, because a “fast” model that fails often is not a good production choice.

### Open-source model inclusion

Open-source models can be compared alongside hosted models using OpenAI-compatible clients:
- **Ollama (local)** for running models on your machine with an OpenAI-style API endpoint
- **OpenRouter** for hosted access to open models behind a unified API

This makes it easy to benchmark “paid vs local vs open” on the same workload and hardware.

### Notes on the design (why it’s structured this way)

This is deliberately minimal and practical:
- **Python is the reference**: baseline behaviour defines correctness.
- **Prompt-as-contract**: models must return only C++ code, optimised for speed.
- **Artefact persistence**: every model’s C++ is saved so you can diff, audit, and reuse.
- **Failure-aware benchmarking**: compile/runtime failures are attributed to the model output, not silently mixed into system errors.
- **Per-task selection**: different optimisation tasks can favour different models; this benchmark is meant to be re-run per workload type.

### Interface

Batch benchmark:
`python_to_cpp_performance(models=[...], python="...", ui_launch=False) -> dict`

- returns Python baseline result/runtime plus, per model:
  - status (`ok`, `llm_compile_error`, `llm_runtime_error`, `skipped_no_client`, etc.)
  - parsed result/runtime when successful
  - speedup factor vs Python

### Demo app (Gradio)

A lightweight Gradio UI is included for interactive use: paste Python code, select a model, and generate the C++ port as a quick inspection / iteration loop (single-model conversion, not the full benchmark loop).

- entry point: `python_to_cpp_performance(ui_launch=True)`
- run locally:
  - ensure required keys are set (`OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`, plus optional `OPENROUTER_API_KEY`)
  - launch: call the function with `ui_launch=True` from inside a `uv run python` session (opens in browser)

---
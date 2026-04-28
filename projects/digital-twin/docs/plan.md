# Digital Twin — Implementation Plan

**Purpose:** An AI agent that represents Alejandro de la Fuente professionally. It answers questions from recruiters and professional contacts about his experience, skills, research, and projects with accuracy, appropriate depth, and a professional tone.

**Audience for this document:** Future sessions building this system. Directional, not instructional — describes what each component is, why it exists, and how components relate. Implementation details belong in code.

---

## System Overview

The system is a RAG-based conversational agent with four layers of concern: knowledge retrieval, answer generation, quality guardrails, and observability. These layers are loosely coupled — each has a clear boundary — so they can be built and evaluated independently before being wired together.

```
User query
    │
    ▼
Main Agent
    ├── RAG pipeline (retrieval + generation)
    ├── Guardrail agent (quality gate)
    ├── Tool: log_unknown_question
    └── Tool: log_user_details
         │
         ▼
    HF Dataset logs
```

---

## Component 1: Knowledge Base and Ingestion

The knowledge base is 15 curated Markdown files in `data/knowledge_base/`. They are the only ingestion source — raw files in `data/raw_me/` are not ingested directly.

**Summary file**
A structured, aggregate-focused document that captures cross-file facts: publication counts, years of experience, skill lists, talk counts, role history at a glance. It is embedded as a single un-split chunk and retrieved like any other chunk. Its value is that it arrives whole — never fragmented — making it reliable for numerical and holistic queries.

**Chunking strategy**
Files are split on `##` and `###` heading boundaries, preserving the heading as part of the chunk so context is never lost. Starting granular (at `###`) gives higher retrieval precision and more retrieval candidates per query. If eval metrics show chunks are too small to carry enough context, the strategy can be widened to `##` only. Heading level and source file are stored as metadata alongside each chunk.

**Embedding**
`text-embedding-3-small` at ingestion time and at query time. The corpus is small and curated, so smaller model capacity is unlikely to be the bottleneck. If retrieval eval reveals weaknesses on specific categories, switching to `text-embedding-3-large` is a one-line change and a re-ingest. ChromaDB is the vector store.

Ingestion is a periodic operation — run once to bootstrap, then re-run when meaningful new content is added to the knowledge base (roughly every few months).

---

## Component 2: RAG Pipeline

**Retrieval**
Two-pass retrieval: the original query and a rewritten query (produced by an LLM that refines the question for knowledge base search) are each used to fetch chunks. Results are merged and deduplicated, then LLM-reranked against the original question. The final top-k chunks are passed to the generation step.

The retrieval-k and final-k values are starting points to be tuned against eval metrics, not fixed constants.

**Generation**
The main agent receives retrieved chunks, conversation history, and a system prompt that establishes the persona and tone. Responses follow a natural conversational structure — direct answer, supporting context, relevant links where available. The agent does not fabricate — if it cannot answer from the retrieved context, it says so and triggers the unknown question log.

**RAG as a tool**
In the retry loop (see Guardrail), the main agent has access to RAG as an explicit tool it can invoke to fetch additional context before reattempting an answer. This gives the agent autonomy to seek more information rather than simply rephrasing the same answer.

---

## Component 3: Evaluation System

Evaluation covers two dimensions — retrieval quality and answer quality — and is run as a unified pipeline that writes both results to a single output file.

**Retrieval evaluation**
Measured against `eval/tests.jsonl` (149 ground-truth Q&A pairs across 7 categories). Metrics: MRR, nDCG, and keyword coverage. These measure whether the right chunks are being surfaced, not whether the answer is good.

**Answer evaluation**
LLM-as-a-judge scoring on four dimensions: accuracy, completeness, relevance, and appropriateness (tone, professional register, no hallucinated credentials). Scores are 1–5. Appropriateness is specific to this use case — it is where answer quality and guardrail concerns overlap.

**Output format**
Results are written to `eval/results/` as versioned JSON files (`v{N}_{date}.json`). Each file contains the architecture version, date, per-question scores, aggregate scores by category, and a `notes` field for a plain-language summary of what changed and why. This structure makes it possible to compare eval runs across different configurations without relying on date inference.

Eval runs are local. Results are committed to the repo after each meaningful evaluation cycle.

---

## Component 4: Main Agent

The main agent is the system's coordinator. It owns the conversation, calls the RAG pipeline, receives guardrail feedback, and decides whether to retry. It has three tools available:

**RAG tool**
Fetches additional context from the vector store. Used in the retry loop when the guardrail flags an answer and more information might resolve the issue.

**log_unknown_question**
Called explicitly by the agent when it determines it cannot answer a question from the available context. The agent does not guess — it calls this tool. The question and session ID are recorded to the unknown questions log.

**log_user_details**
Called at the end of a conversation when the agent invites the user to share contact details. Fields are: name, company, role, email, phone — all optional. The Pydantic model defaults everything to `unknown`. The invitation is framed as: "if you'd like Alejandro to follow up or just want to leave a note that you stopped by."

---

## Component 5: Guardrail Agent

A lightweight, fast LLM call that runs after every answer the main agent produces, before it is returned to the user. Its only job is to determine whether the answer is acceptable.

**Output schema**
```
is_acceptable: bool
feedback: str
```

The guardrail looks for: prompt injection attempts, requests to leak personal/private information, jailbreaking patterns, answers that are factually wrong about Alejandro, and tone or register that would misrepresent him professionally.

**Retry loop**
If `is_acceptable` is `False`, the feedback is added to the main agent's context and it reattempts, optionally fetching additional context via the RAG tool. The user sees a message like "that's a tricky one, let me think a bit longer" during the retry. Maximum 2 retries. If the answer remains unacceptable after 2 attempts, a canned refusal is returned and the interaction is logged.

**Tracking**
Every answer is logged with its `is_acceptable` outcome and the original question, regardless of whether retries were needed. The retry count per interaction is also logged. This data surfaces patterns over time — questions that consistently trigger the guardrail indicate content gaps or prompt issues to address.

---

## Component 6: Logging and Persistence

Three append-only JSONL logs, stored in a private HuggingFace Dataset repository. The Space writes to the dataset via the HuggingFace Hub API using a write token stored in Space secrets. Logs survive Space restarts.

**user_sessions.jsonl**
Session ID, timestamp, full question history, user-provided contact details (if any), and per-answer `is_acceptable` outcomes with retry counts.

**unknown_questions.jsonl**
Question text, session ID, timestamp. Linked to the session so unknown questions can be read in the context of what else the user asked.

**unacceptable_answers.jsonl**
Question, generated answer(s), guardrail feedback per attempt, final outcome (refusal or eventual pass), session ID.

Eval results are separate — they live in `eval/results/` on disk and are tracked in the repo.

---

## Component 7: Deployment

HuggingFace Spaces with a Gradio chat interface. The Space uses the OpenAI API for embeddings and LLM calls, with the API key stored in Space secrets.

The interface is intentionally simple: a chat window, no retrieval context panel (unlike the development evaluator). The experience should feel like talking to a knowledgeable representative, not interacting with a visible RAG system.

The Space is the public surface — linked from the portfolio. The Gradio interface should reflect a professional tone consistent with how Alejandro presents himself.

---

## Phases

**Phase 1 — Core RAG pipeline**
Summary file, chunker, embeddings, ChromaDB store, basic retrieval and generation, Gradio UI. The goal is a working system that can answer questions from the eval set, even if not optimally.

**Phase 2 — Evaluation baseline**
Run the full eval suite against Phase 1. Establish baseline MRR, nDCG, keyword coverage, and LLM-as-judge scores. Identify the weakest categories. This informs all subsequent tuning decisions.

**Phase 3 — Guardrail and agent tooling**
Guardrail agent, retry loop, `log_unknown_question` tool, `log_user_details` tool. HF Dataset logging wired up. Retry UX message in place.

**Phase 4 — Tuning**
Use eval results to tune: chunk granularity, retrieval k, reranking, prompt. Re-run eval after each meaningful change. Version results.

**Phase 5 — Deployment**
Package for HF Spaces. Configure secrets. Smoke test the full interaction flow including guardrail, tools, and logging. Link from portfolio.

---

## What "done" looks like

- Retrieval eval: MRR and nDCG above 0.75 across most categories, with no category below 0.5
- Answer eval: accuracy and appropriateness above 4.0/5 on average
- Guardrail: `is_acceptable = True` on the first attempt for all eval set questions
- Logging: all three logs writing correctly to HF Dataset, session linkage intact
- Deployment: Space live, accessible from portfolio, response latency acceptable for a chat interface

These are directional targets, not hard acceptance criteria. The eval infrastructure exists precisely so these can be measured and revisited.

---

## Constraints and non-goals

- The system represents one person's professional life on a personal website. It is not designed for scale.
- No live web fetching in v1. The knowledge base is the authoritative source.
- No LLM-derived chunking. Structure is exploited directly via heading boundaries.
- The guardrail is a quality gate, not a content moderator for general misuse. Its scope is narrow: protect the representation of Alejandro and prevent the conversation from going somewhere harmful or embarrassing.
- `agentic_ai_lab.md` is deferred until the digital twin itself has a public demo.

# Digital Twin — Decisions and Roadmap

**Project:** AI chat system representing Alejandro de la Fuente professionally  
**Core concept:** A RAG system that answers recruiter and professional questions about skills, experience, projects, and research — with enough depth to be genuinely useful, and links to go deeper.

---

## Session 5 (2026-04-25) — Full raw_me Audit and Link Completeness

### What was audited
All 61 raw_me files checked systematically against every KB file. Verdict: no meaningful content gaps remain. Four targeted fixes applied.

### Changes made
- `publications.md` — added DOI for Iriarte et al. 2021 (viscacha, URL: ojs.sarem.org.ar), PDF download link for Gallardo et al. 2018, Dryad search URL in header
- `education.md` — added MSc thesis title ("Implementation of GIS and species distribution models on studies of niche marginality of threatened plants") and its methodological significance as precursor to PhD SDM work
- `projects_ai_flagship.md` — added Engineering Patterns section (6 cross-cutting patterns from llm-engineering-lab.md portfolio page: prompt contracts, stage-based orchestration, evaluation-first, observability, workflow-ready outputs, resumable async jobs); added explicit HuggingFace dataset names for LLM Price Predictor
- `INDEX.md` — added academic portfolio URL, ORCID direct URL, Dryad search URL, Bird population trends Shiny app URL

### Files confirmed complete (no changes needed)
research_overview, research_projects_detail, recognition, teaching, talks, personal, positioning, skills, experience, identity, projects_skill_labs — all confirmed complete against their raw sources.

### Files with no unique content (skipped)
datascience-communication.md, datascience-projects.md, academic.md (navigation pages); mlb_analytics_sql.md, python-ML-projects.md, python_oop_minisystems.md, python_eda_mini_projects.md (portfolio pages already covered); relevant_links.txt (3 links already in INDEX); summary.txt (2 lines, nothing new).

### Eval: 143 → 149 questions (+6)

---

## Session 4 (2026-04-25) — Personal Content, Project Depth, Production Signals

### What was built

**New KB file:**
- `personal.md` — character, volunteering history as character evidence (wildlife rehab Spain/Portugal/Peru/Bolivia/UK, primate rescue, big cat monitoring), hobbies (MTG, wildlife), working style, what he's looking for

**Enriched existing files:**
- `projects_ai_flagship.md` — Expert Knowledge Worker elevated to full technical section: baseline vs optimised pipeline, LLM-based chunking (headline/summary/original_text), hierarchical RAG via category summaries, query rewriting + LLM reranking, full evaluation system (MRR + nDCG + LLM-as-judge)
- `projects_ai_flagship.md` — AI-JIE: added `instructor` library role, LLM-as-judge v9g baseline (2.98/3.00), eval tracking in eval_results/, GitHub Actions CI, unit tests (idempotency + corruption tolerance)
- `INDEX.md` — added personal.md

**Eval set expanded: 130 → 143 questions (+13)**
- New questions cover: personal.md (5), Expert Knowledge Worker depth (4), AI-JIE CI/evaluation (3), character/working style (1)

---

## Session 3 (2026-04-25) — AI/DS Content Enrichment and Eval Expansion

### What was built

**New KB file:**
- `positioning.md` — explicit bridge narrative: the 5 transfer mechanisms (evaluation discipline, uncertainty quantification, first-principles framing, systems-level thinking, transparent communication), concrete research↔AI parallels table, what Alejandro does not bring

**Enriched existing files:**
- `projects_ai_flagship.md` — Job Intelligence Engine: full 5-stage pipeline architecture added (normalisation, market learning, profile mapping, suitability/competitiveness separation, counterfactual upskilling with stretch→best-now promotion)
- `research_overview.md` — added press/pulse climate effects distinction (birds respond to press, possums to pulse) and its implications for monitoring and conservation
- `INDEX.md` — updated to include `positioning.md`

**Eval set expanded:**
- 100 → 130 questions (+30 new)
- New questions cover: `positioning.md` (5), `research_projects_detail.md` (9), `talks.md` (4), `publications.md` technical summaries (7), Job Intelligence Engine depth (5)
- Distribution: direct_fact 46, numerical 18, comparative 17, relationship 15, temporal 15, holistic 12, spanning 7

---

## Session 2 (2026-04-25) — Knowledge Base Enrichment

### What was built

**Enriched existing files:**
- `publications.md` — added `**Technical summary:**` to every first-author paper (data used, model/method, key decision, output) and added an *Under Review* section for the altitudinal migration manuscript
- `projects_ai_flagship.md` — added final ensemble performance metrics (MAE $29.95, R² 86.3%) and updated AI-JIE model reference to `gpt-5.4-mini`
- `research_overview.md` — added 7th key PhD contribution (altitudinal migration, under review)

**New files created:**
- `research_projects_detail.md` — 9 research project technical case studies (Problem / Approach / Stack / Results / Impact / Data links): mechanistic possum framework, altitudinal migration, community reshuffling, spatiotemporal bird models, possum population viability, SDM→abundance ML, bird trends + Shiny app, biogeochemical cascades, forest gap GLMs
- `talks.md` — all 15+ conference presentations and posters (2017–2025) in table format, with awards and key context

**Index updated:** `INDEX.md` updated to include the two new files and updated descriptions.

### Source material used
All four README files uploaded to `raw_me/` (`README.md`, `README (1).md`, `README (2).md`, `README (3).md`) plus the 9 research project case study files (`bird-elevational-migration.md`, `dynamic-community-reshuffling.md`, etc.) and all conference talk files.

---

## Session 1 (2026-04-24) — Knowledge Base and Evaluation Set

### What was built

**Knowledge base** (`data/knowledge_base/`) — 11 clean Markdown files synthesised from 55+ raw portfolio files, LinkedIn PDF, and AI CV PDF. Raw files had Jekyll front matter, liquid template logic, and redundant content stripped. Organised by topic so each file is independently retrievable:

| File | Coverage |
|---|---|
| `INDEX.md` | Master index + quick-facts for common recruiter questions |
| `identity.md` | Professional narrative, career arc, character, contact, links |
| `skills.md` | Full technical stack — AI/LLM, ML, data, statistical methods |
| `experience.md` | Complete work history with role scope and context |
| `education.md` | Degrees, certifications, courses, self-directed study |
| `projects_ai_flagship.md` | LLM Engineering Lab, AI-JIE, Job Intelligence Engine |
| `projects_skill_labs.md` | MLB SQL, Python ML/OOP/EDA skill labs |
| `research_overview.md` | PhD (tropical montane biodiversity) + postdoc (flying foxes) |
| `publications.md` | All papers: citation, lay summary, DOI link |
| `recognition.md` | Awards, grants, 15 threatened species nominations, media |
| `teaching.md` | Teaching history and student mentoring |

**Evaluation set** (`eval/tests.jsonl`) — 100 ground-truth Q&A pairs covering 7 question categories: `direct_fact` (25), `temporal` (15), `comparative` (15), `numerical` (15), `relationship` (15), `spanning` (5), `holistic` (10). All validated: JSON structure, field names, types, and category names confirmed clean.

---

## Decisions made

### 1. Knowledge base design: summary + links, not full content
Raw files contained 200KB+ of content with heavy redundancy (same information in the CV, LinkedIn, portfolio pages, and individual paper pages). The knowledge base consolidates to ~50KB / ~12,500 tokens, retaining:
- The information needed to answer questions directly
- Technical and lay summaries of papers and projects
- Links to primary sources (GitHub, DOIs, live apps, HuggingFace) for depth

**Rationale:** A RAG system for this use case is answering conversational questions, not reproducing documents. Links handle the "show me the full thing" case without polluting retrieval with noise.

### 2. Chunking strategy: split by `##` headings, not fixed token count
Total corpus is ~12,500 tokens — small enough to fit in a single LLM call. But retrieval precision still requires chunking. Files like `projects_ai_flagship.md` and `publications.md` cover multiple distinct sub-topics in ~2,000 tokens each. Retrieving a full file when only one section is relevant degrades answer quality.

**Decision:** Split on `##` headings (logical sections), not fixed character windows. This yields ~25–35 focused chunks, each covering one paper, one project, or one experience block. No overlap strategy needed at this corpus size.

### 3. Web fetch: links-as-pointers, no live fetch in v1
For a personal digital twin answering known facts about a known person, live web fetch adds latency and failure modes for no benefit. The knowledge base is the authoritative source.

**Exception identified:** GitHub READMEs. The knowledge base has project summaries but not implementation-level details (setup, architecture decisions in README form). A targeted fetch of specific GitHub READMEs on demand is the one addition that would meaningfully expand the system's depth — see roadmap below.

### 4. Evaluation-first approach
The eval set was built before the RAG pipeline so that architectural decisions (chunking strategy, retrieval depth, prompt design) can be measured rather than guessed. Target metrics: MRR, nDCG for retrieval quality; LLM-as-judge for answer quality. The 7-category structure tests the full spectrum from single-chunk lookups to multi-file synthesis.

---

## Knowledge base gaps identified

These are known omissions that should be addressed before or during RAG development:

1. **GitHub READMEs not ingested** — the flagship projects (LLM Engineering Lab, AI-JIE, Job Intelligence Engine) have detailed READMEs with setup instructions, architecture diagrams, and implementation notes that are not in the current knowledge base. A recruiter or technical user asking implementation-level questions will hit this gap.

2. **Thermoregulation research (postdoc)** — the Olivia Bond student project is summarised in `research_overview.md` and `teaching.md`, but there is no standalone document for this specific research thread, which is the most current active work.

3. **Conference talks not represented** — ~15 conference talks are in the raw files but not in the knowledge base. Useful for questions like "has Alejandro presented this work publicly?" A single `talks.md` with a table would address this.

4. **Agentic AI lab projects** — the `llm-engineering-lab.md` covers the GitHub repo, but the ongoing agentic-ai-lab work (including this digital twin) is not represented. Worth adding once there is something to say.

---

## Roadmap

### Phase 1: Core RAG pipeline (next session)

**Ingestion**
- [ ] Section-based chunker: split each `knowledge_base/*.md` file on `##` headings, preserve filename and section header as metadata
- [ ] Embed with `text-embedding-3-small` (OpenAI) or `all-MiniLM-L6-v2` (local, already used in LLM Lab) — decide based on whether the system will be deployed or run locally
- [ ] Store in ChromaDB with metadata: `source_file`, `section_heading`, `category` (identity/skills/projects/research/publications/recognition)

**Retrieval**
- [ ] Top-k retrieval (start k=5, tune against eval set)
- [ ] Return source metadata alongside chunks so answers can cite which file they came from

**Generation**
- [ ] System prompt establishing the persona: "You are Alejandro de la Fuente's digital twin..."
- [ ] Prompt includes retrieved context + conversation history
- [ ] Structured response format: direct answer → supporting detail → relevant link (if available)

**Interface (v1)**
- [ ] Gradio chat UI (already familiar from LLM Lab) — fast to stand up, sufficient for testing

### Phase 2: Evaluation and tuning

- [ ] Run `eval/tests.jsonl` against the pipeline
- [ ] Measure retrieval: MRR, nDCG, chunk hit rate per category
- [ ] Measure answer quality: LLM-as-judge (accuracy, completeness, relevance) — reuse the eval harness pattern from LLM Lab
- [ ] Identify failure modes by category (direct_fact vs holistic should behave very differently)
- [ ] Tune: chunk size, k, prompt, reranking if needed

### Phase 3: Knowledge base expansion (informed by eval failures)

- [x] **GitHub README ingestion** — done in Session 2 from raw_me READMEs; content integrated into existing project files
- [x] Add `talks.md` — done in Session 2
- [ ] Add `agentic_ai_lab.md` — brief entry for this project once it has a demo or public form

### Phase 4: Deployment (optional)

- [ ] Package as a FastAPI endpoint + Gradio or simple chat UI
- [ ] Host on Hugging Face Spaces or as a Streamlit app alongside Job Intelligence Engine
- [ ] Consider adding to portfolio site as a live "talk to me" feature

---

## To-do list

Everything needed before the RAG pipeline is fully ready. Items are grouped by type and ordered by priority within each group.

---

### Knowledge base — content gaps (complete before or alongside RAG build)

**Publications: add technical summaries**
- [x] `publications.md` — technical summaries added to all 7 first-author papers (data, model/method, key decision, output)
- [x] Co-authored papers: Siri et al. 2025 annotated with Alejandro's specific technical role (designed GLM analytical framework)

**Projects: deepen AI flagship entries**
- [x] `projects_ai_flagship.md` — LLM Engineering Lab: supporting projects already had good one-line summaries from Session 1; final ensemble result (MAE $29.95, R² 86.3%) added in Session 2
- [x] `projects_ai_flagship.md` — AI-JIE: model reference, instructor library, CI, unit tests, LLM-as-judge v9g baseline added (Session 4)
- [x] `projects_ai_flagship.md` — Job Intelligence Engine: full 5-stage pipeline + suitability/competitiveness/counterfactual detail added (Session 3)
- [x] `projects_skill_labs.md` — MTG Mana Calculator: one-liner is sufficient given KB coverage in personal.md

**Projects: ingest missing project files from `raw_me`**
- [x] All 9 research case study files ingested as `research_projects_detail.md` (Session 2):
  - `bird-elevational-migration.md` — altitudinal migration, Bayesian N-mixture workflow
  - `dynamic-community-reshuffling.md` — community reshuffling spatial forecasting
  - `heightened-protection-bird-trends.md` — time-series GLMs + Shiny app
  - `physiological-stress-climate-populations.md` — holistic Bayesian framework
  - `spatiotemporal-bird-climate-impacts.md` — Bayesian spatiotemporal models
  - `predicting-abundance-from-niche-theory.md` — ensemble ML (SDM → abundance)
  - `forecasting-popviability-ringtails.md` — Bayesian hierarchical forecasting
  - `ecosystem-pathway-cascades.md` — biogeochemical pathway cascades
  - `forest-gap-abundance-gradients.md` — forest gap GLMs

**Talks: add missing file**
- [x] `talks.md` created (Session 2) — all 15 raw talk files ingested: table of presentations with year, title, venue, location, awards; context block for key talks (CBCS YouTube, CodeR materials, IBRC solar radiation finding)

**Research: standalone postdoc entry**
- [x] Flying fox postdoc fully described in `research_overview.md` (research question, scale, methods, conservation application, student project) — sufficient as its own `##` chunk for retrieval

**GitHub READMEs: fetch and summarise**
- [x] **LLM Engineering Lab** README — ingested from `raw_me/README (1).md`; full 11-project detail now in `projects_ai_flagship.md` including supporting projects, pipeline stages, ensemble results
- [x] **AI-JIE** README — ingested from `raw_me/README (2).md`; model reference, evaluation framework, dataset structure updated in `projects_ai_flagship.md`
- [x] **Job Intelligence Engine** README — ingested from `raw_me/README.md`; pipeline architecture and suitability/competitiveness distinction present in `projects_ai_flagship.md`
- [x] **MLB Analytics** README — ingested from `raw_me/README (3).md`; key findings and SQL techniques in `projects_skill_labs.md`

**Agentic AI Lab**
- [ ] Add `agentic_ai_lab.md` once the digital twin (this project) has a working demo or public form — describe what it is, how it's built, and link to it

---

### Evaluation set — expand alongside KB growth

- [x] Eval set expanded from 100 → 130 questions in Session 3 (covers research_projects_detail, talks, publications technical summaries, positioning, JIE pipeline depth, altitudinal migration manuscript)

---

### RAG pipeline (build next)

See Phases 1–4 in the Roadmap section above.

---

## On the GitHub README question

**Recommendation: add README summaries to the knowledge base, not raw READMEs, and definitely not code explanations.**

| Option | Verdict | Reason |
|---|---|---|
| Links to GitHub (current) | Good baseline | Covers "where can I see this?" but can't answer implementation questions |
| README summaries in KB | Recommended | Adds setup context, architectural notes, and implementation details without noise. Write them the same way as current project files — technical summary + key decisions + stack. |
| Raw README ingest | Avoid | READMEs have badges, install instructions, code blocks — high noise for retrieval, low signal for conversational Q&A |
| Code explanation files | Avoid | Too much volume, goes stale immediately, answers questions no recruiter actually asks. The code is on GitHub; the link handles it. |

The right boundary: the knowledge base should be able to answer "how does the chunking work in the Expert Knowledge Worker project?" but not "what does line 47 of `ingest.py` do?" The former requires a sentence in a README summary; the latter requires reading the code.

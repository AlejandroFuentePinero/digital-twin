# Job Intelligence Engine

**Source:** https://github.com/AlejandroFuentePinero/job-intelligence-engine
**Live app:** https://job-intelligence-engine.streamlit.app/

## What it is

A deterministic, end-to-end **job-market intelligence system** that converts raw job postings into interpretable market signals (skill demand, salary drivers) and a constraint-aware recommender that separates **best-now roles** (high fit, low barrier) from **stretch roles** (high directional fit, clear gaps), with an **ROI-ranked upskilling plan** grounded in observed demand. Surfaced via a deployed Streamlit app.

The deliberate framing: most career advice is generic; even when data exists, it rarely translates into concrete decisions. This system makes the trade-offs **legible** — which roles are realistic now, which are worth stretching for, and what to learn next that will *materially* change the set of roles you can target.

## Architecture

End-to-end pipeline organised as **production-style chapters**, each producing a small set of stable persisted outputs that downstream chapters consume rather than recomputing.

### Stage 1 — Normalisation

- Title standardisation, seniority inference, location/sector metadata, salary field parsing and imputation, structured skill-token extraction.
- Output: clean, joinable job dataset with a consistent schema.

### Stage 2 — Market learning

- **Probabilistic skill-requirement model** smooths noisy binary skill keywords into a calibrated **per-job skill-demand probability layer** — a job × skill matrix of demand probabilities, not raw keyword indicators.
- **Salary response model** (XGBoost/LightGBM + SHAP) captures how job attributes and skill combinations relate to compensation; SHAP values produce per-feature interpretability.
- Output: market representation that downstream pipelines and the app can reason over.

### Stage 3 — Profile mapping

- User's current skill profile embedded into the same skill space as jobs using **SBERT semantic embeddings** — enables like-for-like comparison rather than literal keyword matching.

### Stage 4 — Suitability vs competitiveness separation

- **Suitability** = how well current profile fits requirements.
- **Competitiveness** = barrier to entry driven by missing rare-skill requirements + seniority/pay expectations.
- Job search typically conflates these; separating them is the system's central insight:
  - **Best-now** = high suitability + low competitiveness barrier
  - **Stretch** = high directional fit + clear closeable gaps

### Stage 5 — Counterfactual upskilling

- Hold the job universe constant; simulate adding each missing skill family one at a time; recompute positioning; rank skills by **measurable lift** including stretch→best-now promotion effects.
- Output: per-skill counterfactual ROI — what changes in your candidate set if you learn this.

### App build

`ch5_app_build` pipeline assembles app artefacts from upstream stage outputs into a single "app-ready" surface. Streamlit reads only the assembled artefacts; no live training or recomputation at request time.

## Key engineering decisions

- **Suitability vs competitiveness separation as the system's central insight.** Most "job match" tools collapse fit and barrier into one score. Separating them surfaces the actionable distinction: roles you should apply to *now* vs roles worth *building toward*.
- **Pipeline chapters with stable outputs, not ad-hoc scripts.** Each chapter is an executable pipeline producing a small set of persisted artefacts. Downstream consumers (recommender, explanations, upskilling views) don't re-run the chapters — they read the artefacts. Predictable, auditable, faster to validate when one part changes.
- **Counterfactual upskilling rather than generic advice.** "Learn React" is generic; "Learn React: simulated lift = +12 stretch roles, including 3 stretch→best-now promotions, no impact to current best-now set" is decision-grade. The counterfactual simulation grounds recommendations in observed demand rather than guesswork.
- **Skills extracted from text are noisy proxies, not ground truth.** The probabilistic skill-demand layer smooths keyword noise; the SBERT embedding layer handles semantic equivalents. Both are required because raw keyword matching is too brittle for real job-text variability.
- **Salary parsing and imputation as a first-class step.** Compensation fields in raw postings are sparse and heterogeneous; the salary response model needs them imputed consistently. Handled in stage 1, not papered over downstream.
- **App build as a separate, validated stage.** The recommender, explanations, and upskilling views aren't standalone scripts — they're assembled from upstream pipeline outputs. The build step gathers required artefacts across the project into a single app-ready surface and validates their presence before Streamlit starts. Clean failure mode: missing artefact → build fails loud; not "app silently shows stale data."

## Scope and limitations (honest framing)

The project is **scope-locked at v1**. The output is decision support, not hiring guarantees. Honest limitations documented in the technical report:

- **Job ads are noisy proxies** — postings reflect stated requirements, not actual hiring decisions.
- **Dataset bias** — coverage is limited to Kaggle source datasets and their time/region mix.
- **Skills are text-derived** — extracted tokens can miss context (e.g., "nice to have" vs "required").
- **Salary fields are imperfect** — sparse and heterogeneous, parsed/imputed where possible.
- **Decision support, not causality** — outputs are correlational signals to guide targeting and upskilling.

## Stack

Python · pandas · NumPy · scikit-learn · SBERT · XGBoost / LightGBM · SHAP · Streamlit · NetworkX

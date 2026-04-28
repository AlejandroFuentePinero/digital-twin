# Job Intelligence Engine
A deterministic, end-to-end job-market intelligence system that converts job ads into interpretable market signals and a constraint-aware recommender (**best-now** vs **stretch**) surfaced via a lightweight [Streamlit app](https://job-intelligence-engine.streamlit.app/).

![Job Intelligence Engine — engine path](media/engine_path.png)

## Contents
- [About](#about-the-project)
- [Quickstart](#quickstart)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Reproducibility and scope](#reproducibility-and-scope)
- [Data and licensing](#data-and-licensing)
- [Documentation and Structure](#Documentation-and-repository-structure)
- [Contact](#contact)

## About the project

Most people don’t struggle to work hard — they struggle to choose: which jobs to target, what “good fit” means in practice, and which skills actually change outcomes (instead of just adding noise).

The data job market is especially prone to this problem. Postings are high-volume, inconsistent, and full of overlapping terminology. Advice is often generic, and even when data exists, it rarely translates into concrete decisions: which roles are realistic *now*, which are worth stretching for, and what to learn next to materially improve outcomes.

Job Intelligence Engine turns the market into something you can query. It learns structured signals from real job postings and uses them to position an individual under constraints. The app summarises market patterns, then maps your current profile to **best-now roles**, **stretch roles**, and an **ROI-ranked upskilling plan** grounded in observed demand rather than guesswork.

The motivation is straightforward: reduce job-search noise by making trade-offs legible. Instead of scanning postings one by one, you get an evidence-based view of where you fit, what you’re missing, and which improvements are most likely to change the set of roles you can credibly target.

### **How to read recommendations**
- **Best-now:** high fit with few critical gaps.
- **Stretch:** strong directional fit, but clearer gaps and a higher entry barrier.
- **Upskilling:** ranks missing skill families by simulated lift—how much adding a skill family improves stretch outcomes (including “stretch → best-now” promotions), while penalising changes that harm the current best-now set.

## Quickstart

The fastest way to experience the project is the deployed app.

> [**Live app**](https://job-intelligence-engine.streamlit.app/)

![Job Intelligence Engine — Demo](media/app_demo.gif)

To run it locally, clone the repository, install dependencies, and launch the app. The build step assembles the app assets and validates required artefacts before Streamlit starts.

```bash
git clone https://github.com/AlejandroFuentePinero/job-intelligence-engine.git
cd job-intelligence-engine

python -m pip install -r requirements.txt
python -m src.job_intel.pipelines.ch5_app_build
streamlit run app.py
```
Local run does not train. It loads persisted models and artefacts (built by the pipelines) and assembles an app-ready bundle via `ch5_app_build`.

**Requirements:** Python 3.10+ (3.11 recommended). 

Full environment notes and troubleshooting: `docs/plan_and_structure/how_to_run_v1.md`

## Usage

A typical run follows a simple loop. Start with the market overview to calibrate what the data is rewarding (skills, role structure, and salary signal). Then run the recommender to generate **best-now** and **stretch** roles and inspect the “why” explanations to understand the drivers behind each result. Finally, open the upskilling view to see which skill families produce the largest counterfactual lift and explore the role-level deltas.

The app includes interpretation blocks throughout. For the full set of supported inputs, the demo persona configuration, and deeper guidance on how to interpret outputs, see `docs/narrative/technical_report.md`.

## How it works

Job Intelligence Engine is built as a single, end-to-end pipeline that turns messy job postings into a market representation you can reason about, then uses that representation to produce personalised decision support. It starts by normalising job postings into a consistent dataset (titles, seniority, location/sector metadata, salary fields, and structured skill signals). From there, the system learns the “shape” of the market: a salary response model captures how job attributes and skill structure relate to compensation, and a set of skill-demand models produces a calibrated job × skill probability layer that smooths noisy binary keywords into a reusable demand signal. Those signals also power the app’s market summary and interpretability views.

When a user enters the system, their profile is mapped into the same skill space used for jobs, then hard constraints define a feasible candidate universe. Within that universe, the engine separates two ideas that job search often mixes: **suitability** (fit to the user’s current profile) and **competitiveness** (barrier to entry driven by missing, rare skill requirements and job seniority/pay expectations). The recommender turns those signals into two shortlists—**best-now** and **stretch**—and attaches a simple explanation layer that makes each result inspectable. Upskilling is handled as counterfactual decision support: the system holds the job universe constant, simulates adding missing skill families, recomputes positioning, and ranks skills by measurable lift (including “stretch → best-now” promotion effects), so recommendations stay grounded in observed job-posting demand rather than generic advice.

A full technical description (features, models, evaluation, and artifacts) is provided in `docs/narrative/technical_report.md`, with the canonical system map in `docs/engineering/architecture.md`.


![Job Intelligence Engine — Simple App Workflow](media/project_pipeline_simple.png)

## Reproducibility and scope

Job Intelligence Engine is organised around production-style pipelines. Each chapter is implemented as an executable pipeline that produces a small set of stable outputs (processed datasets, fitted models, and derived market assets). Those outputs are then composed downstream rather than recomputed ad hoc, which keeps the system predictable and makes it easier to validate what changed when you update one part of the engine.

In practice, reproducibility comes from two things: the chapter pipelines that build and validate their outputs, and the app build step that gathers the required artefacts across the project into a single “app-ready” surface. That means the recommender, explanations, and upskilling views are not standalone scripts—they are assembled from upstream pipeline outputs that encode the market signal learned from the data.

The intent is decision support, not hiring guarantees. The engine summarises patterns in job-posting data and converts them into interpretable ranking and gap signals; it is useful for prioritising roles and planning upskilling, but it should not be interpreted as causal claims about what any specific employer will do. Deeper evaluation, assumptions, and limitations are documented in `docs/narrative/technical_report.md`.

### Final scope lock (v1)

This project is **scope-locked at v1**. The app, repo documentation, and technical report are complete and consistent with the current artefact contracts.  
Changes from this point should be limited to **critical bug fixes** (broken links/assets, runtime errors, security) and otherwise deferred to `docs/plan_and_structure/v2_improvements.md` as **v2** work.

**Limitations (high level)**
- **Job ads are noisy proxies:** postings reflect stated requirements, not actual hiring decisions.
- **Dataset bias:** coverage is limited to the Kaggle sources and their time/region mix.
- **Skills are text-derived:** extracted tokens can miss context (e.g., “nice to have” vs “required”).
- **Salary fields are imperfect:** compensation is sparse/heterogeneous and may be parsed or imputed.
- **Decision support, not causality:** outputs are correlational signals to guide targeting and upskilling.

<details>
  <summary><strong>Pipeline map (full system overview)</strong></summary>

  ![Job Intelligence Engine — full pipeline map](media/visual_overview.png)
</details>

## Data and licensing

This project uses two public Kaggle datasets:
- [Data Scientist Jobs](https://www.kaggle.com/datasets/andrewmvd/data-scientist-jobs?select=DataScientist.csv)
- [Data Analyst Jobs](https://www.kaggle.com/datasets/andrewmvd/data-analyst-jobs)

A snapshot of the Kaggle source data used for this project is included under `data/raw/` for reproducibility. Please review Kaggle and the dataset authors’ terms before reusing or redistributing the data.

Code licensing is defined in `LICENSE`.

## Documentation and repository structure

### Project documentation
- `docs/engineering/architecture.md` — canonical system map (modules, pipelines, artefacts)
- `docs/engineering/artefact_manifest_ch5_app.md` — manifest lists every persisted file the app expects at runtime
- `docs/engineering/data_dictionary.md` — engineered fields and definitions
- `docs/narrative/technical_report.md` — full narrative, methodology, and results
- `docs/plan_and_structure/how_to_run_v1.md` — environment setup, local run, troubleshooting
- `docs/plan_and_structure/v2_improvements.md` — scoped, ranked backlog

### Repository structure
![Job Intelligence Engine — Repo Structure](media/repo_structure.png)

## Contact
Alejandro de la Fuente — [GitHub](https://github.com/AlejandroFuentePinero) · [LinkedIn](https://www.linkedin.com/in/alejandro-de-la-fuente-a367a137a/)

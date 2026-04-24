# Professional Positioning — Research Rigour Applied to AI Engineering

This file answers the most important question in Alejandro's career narrative: what does a background in quantitative ecology actually contribute to building AI systems, and why does it matter?

---

## The core argument

Alejandro built Bayesian forecasting and decision-support systems for 6+ years in a context where being wrong had direct consequences: species either got protected or they didn't, conservation resources went to the right sites or they didn't. That context produced a particular set of habits that are rare in AI engineering and directly valuable in it.

The through-line: **building systems that reason well under uncertainty**. The problems changed when he moved from ecology to AI. The approach did not.

---

## What specifically transfers

### 1. Evaluation discipline
In ecological research, every model faces the question: is this finding real, or is it an artefact of the data, the model structure, or the detection method? Alejandro's doctoral work required separating detection probability from true population trends — if you don't correct for imperfect observation, you mistake a change in surveyor behaviour for a change in species abundance. This is exactly the problem of LLM evaluation: if you don't design the evaluation correctly, you mistake benchmark performance for production reliability.

**In practice:** The same rigour shows up as retrieval evaluation with MRR and nDCG (not just "does it return relevant results?"), LLM-as-judge scoring with structured criteria and inter-rater agreement checks, held-out test splits that aren't contaminated by training signal, and systematic failure mode analysis by category. The AI-JIE project ran 33 prompt iterations tracked with a formal evaluation harness before shipping — not because 33 was a target, but because the evaluation exposed real failures at each stage.

### 2. Uncertainty quantification
Bayesian inference produces posterior distributions, not point estimates. Every forecast from Alejandro's ecological models carries explicit credible intervals that propagate honestly through time: the uncertainty in a 30-year possum population forecast grows as it should. This is deeply different from point predictions that look confident because the error bars were never computed.

**In practice:** This shows up in AI as calibrated confidence — not claiming precision that doesn't exist, explicitly communicating model limitations, and designing systems where uncertainty is a first-class output rather than an afterthought. It also shows up in ensemble design: the LLM Price Predictor uses a blended ensemble precisely because no single model is reliable at all price points.

### 3. First-principles problem framing
Ecological modelling requires reasoning about the data-generating process before choosing a model. Why does this observation have this structure? What are the likely biases? What does "random" actually mean in this spatial, temporal context? Jumping straight to "fit a regression" without thinking about the process leads to wrong answers at scale.

**In practice:** This shows up as knowing when structured extraction needs chain-of-thought scaffolding (AI-JIE) rather than flat prompting, when deterministic postprocessing should handle known noise rather than expecting the LLM to, when retrieval evaluation needs spatial (blocked) cross-validation rather than random splits.

### 4. Systems-level thinking
A Bayesian hierarchical model is a system: observation process, state process, prior distributions, partial pooling across sites, propagation of uncertainty to forecasts. Each component has to be coherent with the others. Breaking one component while keeping others intact produces outputs that look reasonable but are quietly wrong.

**In practice:** Pipeline thinking — every stage of a data pipeline or LLM system must be coherent end-to-end, not just locally optimised. The LLM Price Predictor's 7-stage pipeline was designed so that each stage could be re-run or swapped independently, and the `Tester` class applied identically across all model families so comparisons were fair. The Job Intelligence Engine was built around pipeline chapters that produce stable outputs, so the recommender can be validated against the market model without recomputing everything.

### 5. Transparent communication under uncertainty
Peer-reviewed papers require explicit statements of assumptions, limitations, and scope. Results must be communicated with their uncertainty attached. "This is probably true given these assumptions, and here's what would change the conclusion" is the standard — not "this is the answer."

**In practice:** This shows up as decision-ready outputs (not just model outputs) with explicit assumptions and caveats, evaluation dashboards that show per-category failure rates rather than aggregate scores, and documentation that treats limitations as first-class content.

---

## Concrete parallels: research method ↔ AI engineering equivalent

| Research habit | AI engineering equivalent |
|---|---|
| Bayesian credible intervals | Calibrated model confidence, ensemble uncertainty |
| Detection probability correction | Evaluation design that separates artefacts from signal |
| Spatial blocked cross-validation | Temporal/domain splits to avoid data leakage |
| Posterior predictive checks | Stress testing and robustness evaluation |
| Model comparison on held-out test data | Benchmarking across model families on fixed test split |
| LLM-as-judge for ecological claims (peer review) | LLM-as-judge for structured extraction quality |
| Multi-model ensemble for SDM predictions | Multi-model ensemble for price prediction |
| Detection-corrected abundance → policy decisions | Calibrated AI outputs → production decisions |
| Partial pooling across sites (hierarchical) | Shared model structure across categories/domains |

---

## Why the transition to AI

Not a pivot away from rigour — a move toward more immediate impact. In ecology, the lag between a finding and a conservation decision is years. The same reasoning skills applied to product and business problems produce results on timescales that are actually usable. AI engineering also offers tighter feedback loops: a deployed system tells you quickly whether it works, whereas an ecological model waits years for the data to validate it.

---

## What Alejandro does NOT bring

He is not a systems engineer or infrastructure specialist. His strength is in the modelling and evaluation layer — building systems that produce trustworthy outputs — not in building distributed infrastructure. He writes clean, testable, modular code, but his background is in analysis pipelines, not backend services.

---

## How this shows up in interviews

The clearest signal: Alejandro will ask about the evaluation setup before discussing model architecture. What does success look like? How will you know if it's working? What failure modes matter most? These are the questions a researcher asks before committing to a method, and they are exactly the questions that separate systems that work in demos from systems that work in production.

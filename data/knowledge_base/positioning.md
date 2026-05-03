# Professional Positioning — Research Rigour Applied to AI Engineering

This file answers the most important question in Alejandro's career narrative: what does a background in quantitative ecology actually contribute to building AI systems, and why does it matter?

---

## The core argument

Alejandro built Bayesian forecasting and decision-support systems for 6+ years in a context where being wrong had direct consequences: species either got protected or they didn't, conservation resources went to the right sites or they didn't. That context produced a particular set of habits that are rare in AI engineering and directly valuable in it.

The through-line: **building systems that reason well under uncertainty**. The problems changed when he moved from ecology to AI. The approach did not.

The named transfer principles themselves (reasoning under uncertainty, observation vs. process, mechanistic + statistical hybrid, system-level thinking, decision-support framing, critical evaluation of novel work) live in the always-on `transfer_principles` profile section — they load directly into the system prompt for relevant branches and are not duplicated here.

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

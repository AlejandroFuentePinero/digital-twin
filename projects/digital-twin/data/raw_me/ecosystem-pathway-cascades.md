---
title: "Modelling Biogeochemical Pathway Cascades using Bayesian Hierarchical Models"
excerpt: "Revealed ecosystem cascades and biogeochemical pathways in tropical systems using Bayesian hierarchical modelling to quantify direct and indirect effects in complex ecological networks."
tier: research   # featured | learning | research
date: 2024-10-25
---

## Problem
Ecosystems operate through complex direct and indirect interactions—understanding how herbivory cascades through biogeochemical processes is critical but structurally and statistically challenging.  
**Goal:** Model and disentangle direct and indirect pathways of ecosystem functioning using **Bayesian hierarchical models**, clarifying cascading effects in biogeochemical dynamics.

## Approach
- Compiled experiments and observations quantifying herbivory rates, plant defences, nutrient fluxes, and other ecosystem variables in montane rainforests.
- Built **Bayesian hierarchical models** that capture:
  - Direct effects (e.g., plant defences → herbivory)
  - Indirect pathways (e.g., mediated through soil nutrient flux or climatic processes)
  - Random effects across geographical sites (hierarchical nesting).
- Quantified cascading impacts via posterior analysis of structured pathway coefficients.
  
## Stack
- **Hierarchical Bayesian modelling**: direct and indirect effect estimation within structured ecological networks.
- **Biogeochemical pathway analysis**: handling multiple response variables in a network framework.
- **Data workflows**: data integration from field measurements, cleaning, reproducible analysis pipeline.
- **Implementation**: executed in **R** for processing and visualisation, and **JAGS** for model specification, all under version control for transparency.

## Results
- Identified both direct herbivory and mediated biogeochemical effects contributing to ecosystem dynamics.
- Generated quantitative estimates of pathway strengths and uncertainty, revealing cascading structuring across trophic and nutrient cycles.

## Impact
- Advanced understanding of ecosystem functioning by quantifying complex ecological cascades.
- Provided a modelling framework transferable to similar tropical ecosystem studies and management scenarios.

## Links & Resources
- 📄 **Paper:** [Oecologia article](https://link.springer.com/article/10.1007/s00442-024-05630-y)  
- 💾 **Data Repository:** [Dryad dataset](https://datadryad.org/dataset/doi:10.5061/dryad.d51c5b08s)

## Role
- Designed and specified the hierarchical modelling of cascading pathways.
- Cleaned and structured multivariate field dataset.
- Fitted Bayesian models, interpreted complex posterior relationships.
- Wrote the manuscript and articulated the ecological implications.

---
title: "Detecting Climate Impacts on Rainforest Birds Using Bayesian Spatiotemporal Modelling"
excerpt: "Applied hierarchical Bayesian models with satellite-derived predictors to identify climate-driven population changes in rainforest birds across space and time."
tier: research   # featured | learning | research
date: 2023-01-18
---

## Problem
Tropical montane bird populations are increasingly threatened by climate change and extreme events, but detecting climate-driven signals in noisy, long-term monitoring data is challenging.  
**Goal:** Use **Bayesian hierarchical spatiotemporal models** to quantify how climate variables and cyclone impacts drive population change, integrating multi-scale environmental predictors from remote sensing.

## Approach
- Assembled multi-decadal bird abundance datasets across rainforest sites in the Australian Wet Tropics.
- Derived spatiotemporal climate predictors, including temperature, precipitation, and cyclone exposure indices, at the site-year level.
- Processed high-resolution **satellite imagery** to quantify cyclone-induced changes in rainforest vegetation structure.
- Integrated climate and vegetation metrics into a **hierarchical Bayesian framework** to model abundance in a multidimensional space:  
  - State process: latent population dynamics across space and time.  
  - Observation process: detection probability from repeated surveys.
- Ran models in **JAGS** with spatial and temporal random effects, quantifying effect sizes, uncertainty, and spatial heterogeneity in climate impacts.

## Stack
- **Bayesian spatiotemporal modelling**: spatial random effects, temporal trends, and covariate integration.
- **Remote sensing integration**: processed satellite imagery to derive vegetation change metrics.
- **Advanced statistical modelling**: detection–abundance separation, credible interval estimation.
- **Data workflows**: large-scale data cleaning, spatial joins, reproducible analysis pipelines.
- **Implementation**: conducted in **R** for data processing/visualisation and **JAGS** for model specification and inference, under version control.

## Results
- Identified significant negative population responses to cyclone-driven vegetation loss and to climate warming in several species.
- Revealed spatial heterogeneity in climate impact strength, with higher elevations often showing stronger declines.
- Quantified uncertainty, enabling robust interpretation for conservation planning.

## Impact
- Provided direct evidence linking extreme climatic events and long-term warming to bird population declines in the Wet Tropics.
- Informed adaptive management strategies and reinforced the case for targeted conservation action in climate-vulnerable habitats.

## Links & Resources
- 📄 **Paper:** [Global Change Biology article](https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.16608)  
- 💾 **Data Repository:** [Dryad dataset](https://datadryad.org/dataset/doi:10.5061/dryad.hx3ffbgjj)

## Role
- Designed and implemented the spatiotemporal Bayesian modelling framework.
- Processed and integrated satellite-derived vegetation change metrics.
- Conducted model fitting, validation, and uncertainty quantification.
- Interpreted results in the context of climate change impacts and co-authored the manuscript.

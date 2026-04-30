---
title: "Forecasting Population Viability with Bayesian Hierarchical Models"
excerpt: "Developed Bayesian hierarchical models incorporating detection probability to forecast population viability and support elevated conservation status for imperilled species."
tier: research   # featured | learning | research
date: 2022-11-06
---

## Problem
Understanding population sustainability is critical to conservation prioritisation—but count data are often imperfect and biased by detection issues.  
**Goal:** Build robust forecasts of population viability using **Bayesian hierarchical models** that explicitly account for detection probability, to inform elevated conservation listing at national and international levels.

## Approach
- Collated long-term count data with imperfect detection from population monitoring of targeted species.  
- Built **Bayesian hierarchical models**: observation process (detection component) separated from true state process (abundance/trend).  
- Integrated prior knowledge and error structures to model latent population trends and forecast future viability under current and projected conditions.  
- Derived **population viability metrics** (e.g., extinction probability, trend trajectories), feeding decisions for national/international conservation listings.

## Stack
- **Bayesian hierarchical modelling**: detection–abundance partitioning, forecasting of latent trends with credible intervals.  
- **Forecasting workflows**: dynamic prediction of future population trajectories under forecasted climate change, uncertainty quantification.  
- **Data workflows**: count data cleaning, variable development (climate change predictors), model fitting, posterior analysis, reproducible scripting and reporting.  
- **Implementation**: carried out in **R** (data processing, analysis, visualisation) and **JAGS** (Bayesian model specification and MCMC sampling), with full version control for transparency.


## Results
- Forecasted strong declines in target species with credible uncertainty bounds.  
- Identified species with high extinction risk over relevant time horizons.  
- Results directly contributed to elevating conservation priority status for those species under national and international protection lists.

## Impact
- Strengthened the scientific basis for conservation policy decisions by delivering rigorous, uncertainty-aware forecasts.  
- Demonstrated the value of integrating detection-corrected Bayesian models into species viability assessments.

## Links & Resources
- 📄 **Paper:** [Diversity & Distributions article](https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13652)  
- 💾 **Data Repository:** [Dryad dataset](https://datadryad.org/dataset/doi:10.5061/dryad.m63xsj44h)

## Role
- Conceptualised and developed the hierarchical Bayesian framework.  
- Cleaned and structured count/detection data and climate change covariates (heatwaves and warming) for robust inference.  
- Ran forecasting models and interpreted posterior outputs.  
- Produced insights used in elevated conservation recommendations.  
- Wrote the manuscript and communicated findings to conservation authorities.

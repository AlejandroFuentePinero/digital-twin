---
title: "Integrating Microclimate, Physiology, Biogeochemistry, and Population Models to Link Climate Change to Demographic Outcomes"
excerpt: "Developed and implemented a holistic Bayesian framework integrating microclimate, mechanistic physiology, biogeochemical processes, and population dynamics to identify causal pathways from climate change to survival and recruitment."
date: 2025-05-05
tier: research   # featured | learning | research
---

## Problem
Climate change impacts species through complex, interacting mechanisms — from environmental conditions to physiological stress, ecosystem processes, and demographic rates.  
Understanding these links requires integrating multiple models and data sources into a **single, holistic framework** that can reveal causality, not just correlation.

**Goal:** Combine **microclimate modelling**, **mechanistic physiological energetics**, **biogeochemical pathway modelling**, and **Bayesian hierarchical population forecasting** to mechanistically link climate variability and extremes to recruitment and survival in a climate-vulnerable species.

## Approach
- **Microclimate modelling**: simulated fine-scale environmental conditions within roosting habitats to capture species-relevant temperature, humidity, and thermal stress.
- **Physiological modelling**: quantified energetic and thermal balances to estimate climate-driven physiological stress (e.g. dehydration, overheating) at relevant temporal scales.
- **Biogeochemical modelling**: incorporated nutrient cycling and vegetation process models to capture indirect effects on habitat quality and food availability.
- **Population modelling**: developed Bayesian hierarchical models linking physiological and biogeochemical predictors to demographic rates (recruitment and survival), explicitly accounting for detection probability in count data.
- Integrated all components into a **unified Bayesian framework** implemented in **R** and **JAGS**, enabling joint inference and propagation of uncertainty across the entire causal chain.

## Stack
- **Holistic modelling integration**: combining microclimate, physiology, biogeochemistry, and population dynamics within one framework.
- **Bayesian hierarchical modelling**: linking mechanistic covariates to demographic outcomes with full uncertainty propagation.
- **Mechanistic physiological energetics**: modelling metabolic and thermal constraints under changing environments.
- **Data workflows**: multi-source environmental, physiological, and demographic data cleaning and harmonisation; reproducible pipelines.
- **Implementation**: developed in **R** for data processing, integration, and visualisation; **JAGS** for Bayesian model specification and inference.

## Results
- Demonstrated causal pathways from climate variability and extremes to population decline through physiological stress on recruitment and survival.
- Quantified direct and indirect effects, revealing the magnitude of each mechanism and their combined influence on viability.
- Produced fully integrated forecasts, allowing scenario testing for management interventions.

## Impact
- First application to integrate microclimate, physiology, biogeochemistry, and population dynamics in a unified Bayesian framework for conservation.
- Provided a mechanistic, evidence-based foundation for targeted conservation planning under climate change.

## Links & Resources
- 📄 **Paper:** [Global Change Biology article](https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.70215)  
- 💾 **Data Repository:** [Dryad dataset](https://datadryad.org/dataset/doi:10.5061/dryad.fxpnvx13n)

## Role
- Designed and implemented the entire multi-component modelling workflow.
- Developed each model component (microclimate, physiology, biogeochemistry, population) and integrated them into a holistic Bayesian framework.
- Conducted model fitting, validation, and scenario testing.
- Authored manuscript, providing the analytical synthesis and causal interpretation.

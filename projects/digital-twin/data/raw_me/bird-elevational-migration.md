---
title: "Altitudinal Migration and Seasonal Redistribution in Rainforest Bird Communities"
excerpt: "Developed a hierarchical Bayesian workflow to quantify partial altitudinal migration and system-wide community reshuffling across elevation and season in the Australian Wet Tropics."
tier: research   # featured | learning | research
date: 2025-09-15
---

## Problem
Seasonal shifts in abundance along mountain gradients—known as **altitudinal migration**—remain one of the least quantified forms of animal movement. In tropical mountains, these redistributions are subtle and partial, involving only portions of populations moving uphill or downhill seasonally.  
**Goal:** Detect and quantify altitudinal migration at the community scale using long-term bird monitoring data, accounting for imperfect detection and uneven sampling, and identify how species and communities dynamically “breathe” across elevation and season.

## Approach
- Integrated 16 years of imperfect bird count data from the Australian Wet Tropics (2000–2016), spanning >100 rainforest sites across full elevational gradients.  
- Built a **hierarchical Bayesian N-mixture model** to jointly estimate abundance and detection while isolating the seasonal signal of redistribution.  
- Defined altitudinal migration as the **season × elevation interaction**, using ecologically centred season encoding (−0.5 = winter, +0.5 = summer) to directly interpret uphill vs. downhill movements.  
- Pooled across mountains with species-level random slopes to maximise statistical power and capture consistent migration signals.  
- Generated **posterior predictions** of abundance across continuous elevation bands to reconstruct system-wide patterns of seasonal change.  
- Computed derived metrics (centroid shift, range shift, turnover) to quantify redistribution at both species and community levels.

## Stack
- **Bayesian hierarchical modelling**: implemented in **JAGS** with structured priors, shrinkage, and multi-level random effects.  
- **Data engineering & post-processing**: extensive data reshaping, full grid expansion, NA-filling, and prediction-block generation in **R (tidyverse)**.  
- **Model validation**: posterior predictive checks, convergence diagnostics, and cross-season model comparisons.  
- **Downstream analytics**: abundance centroids, elevational range width, beta-diversity turnover (vegan & betapart).  
- **Visualisation**: ggplot2 and patchwork pipelines for system-level “breathing” plots across elevation and season.

## Results
- Most species exhibited **predictable seasonal redistribution**—moving uphill in summer and downhill in winter.  
- These individual shifts aggregate into a striking **community-level pattern**, with total bird abundance peaking in lowlands during winter and uplands in summer.  
- Species-specific centroid and range shifts revealed diverse strategies—from narrow-range specialists showing limited movement to generalists tracking resources more flexibly.

## Impact
- Provides the **first quantitative system-wide evidence** of partial altitudinal migration in tropical rainforest birds.  
- Establishes a generalisable **Bayesian workflow** for detecting redistribution in long-term monitoring datasets.  
- Demonstrates how seasonal migration acts as a **systemic process**, reshaping community structure and potentially buffering biodiversity against climate change.

## Links & Resources
- 📄 **Manuscript:** *Under Review for* *Diversity and Distributions* (Altitudinal migration and community breathing in the Australian Wet Tropics).  

## Role
- Designed the **model architecture** and analytical workflow.  
- Engineered the data processing and prediction pipelines.  
- Led the **Bayesian modeling**, post-processing, and community-level synthesis.  
- Wrote the full manuscript.

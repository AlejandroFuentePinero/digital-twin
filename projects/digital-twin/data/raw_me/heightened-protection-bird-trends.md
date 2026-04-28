---
title: "Assessing Bird Population Trends to Inform Conservation Priorities"
excerpt: "Used time-series GLMs and interactive visualisation (Shiny app) to nominate 14 bird species for elevated protection under national and international priority lists."
tier: research   # featured | learning | research
date: 2021-12-22
---

## Problem
Rapid shifts in bird population trends can signal emerging conservation needs, but time-series data are often under-analysed in policy contexts.  
**Goal:** quantify population trajectories using robust statistical methods and translate results into an **interactive Shiny app** to support decision-making and prioritise protection for vulnerable species.

## Approach
- Compiled long-term monitoring datasets, harmonised time-series counts.
- Fitted **Generalised Linear Models (GLMs)** with time and covariates (e.g., survey effort, habitat changes) to characterise population trends for each species.
- Identified 14 species showing significant declines or vulnerabilities and nominated them for elevated protection under national (e.g., Threatened Species lists) and international frameworks (e.g., IUCN priorities).
- Developed a user-friendly **Shiny application** to visualise trends, allowing stakeholders and policymakers to interactively explore trajectories, confidence intervals, and nomination thresholds.

## Stack
- **Statistical analysis**: GLMs for time-series trend estimation, covariate adjustment, trend significance testing.
- **Data workflows**: cleaning and harmonising multi-source count data, exploratory visualisation, reproducible scripting.
- **Interactive outreach**: built and deployed a **Shiny web app** to share results with managers, NGOs, and decision-makers.
- **Implementation**: conducted entirely in **R**, with version-controlled code on GitHub and transparent deployment.

## Results
- Detected significant declining trends in rainforest bird species.
- Provided robust statistical evidence to support elevated protection recommendations.
- Enhanced accessibility of results through a live, interactive Shiny app.

## Impact
- The findings directly informed formal nominations for elevated protection under national and international priority frameworks.
- Shiny app promoted transparency and stakeholder engagement, facilitating policy uptake and broader awareness.

## Links & Resources
- 📄 **Paper:** [PLOS ONE article](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0254307)  
- 🌐 **Interactive app:** [Shiny App – Bird Population Trends](https://alejandrodelafuente.shinyapps.io/BirdsPopTrendAWT/)

## Role
- Designed and conducted the analytical workflow (GLMs and trend detection).
- Harmonised complex time-series datasets.
- Built and deployed the Shiny app for outreach and transparency.
- Drafted the manuscript and coordinated conservation policy communication.

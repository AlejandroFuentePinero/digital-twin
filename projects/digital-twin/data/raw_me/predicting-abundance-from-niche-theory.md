---
title: "Predicting Species Abundance from Environmental Suitability"
excerpt: "Applied ensemble machine learning to convert presence-only niche models into abundance predictions, combining big-data wrangling, advanced analytics, and multi-algorithm ensembles."
tier: research   # featured | learning | research
date: 2021-10-12
---

## Problem
Conservation and land-use planning require **maps of abundance**, not just where a species can occur. Traditional surveys are expensive and spatially limited; presence-only data are abundant but lack counts.  

**Goal:** Build a reproducible, data-driven workflow that predicts **continuous abundance** from environmental suitability, using **ensemble machine learning** to combine multiple niche modelling algorithms and link them to observed counts.

## Approach
**1) Data acquisition & wrangling**  
- Integrated large-scale presence-only data, count surveys, and high-resolution climate/topography layers.  
- Cleaned, standardised, and processed data for 23 focal species across tropical systems.  
- Automated feature extraction and alignment across spatial grids.  

**2) Suitability modelling (multi-algorithm ensemble)**  
- Trained individual models using:  
  - Surface Range Envelope (SRE)  
  - Classification Tree Analysis (CTA)  
  - Random Forest (RF)  
  - Multivariate Adaptive Regression Spline (MARS)  
  - Flexible Discriminant Analysis (FDA)  
  - MaxEnt  
  - Generalised Additive Models (GAM)  
  - Generalised Boosted Regression Models (GBM)  
  - Artificial Neural Networks (ANN)  
- Combined predictions into an **ensemble suitability surface** for each species.  

**3) Linking suitability to abundance**  
- Modelled observed abundance as a flexible function of suitability (tested multiple link functions).  
- Accounted for sampling effort and detectability.  
- Validated with **spatial cross-validation** to avoid overfitting.  

**4) Delivery**  
- Produced spatially explicit abundance maps with **uncertainty bands**.  
- Exported gridded rasters and tabular summaries for stakeholders.  

## Stack
- **Advanced statistical modelling**: generalised linear models (GLM), generalised additive models (GAM), boosted regression, multivariate adaptive regression splines.  
- **Machine learning**: tree-based ensembles, discriminant analysis, MaxEnt, artificial neural networks.  
- **Data workflows**: large-scale data wrangling, geospatial processing, exploratory analysis, visualisation, and fully reproducible pipelines.  
- **Implementation**: all modelling, analysis, and visualisation conducted in **R** with version control.  

## Results
- Strong suitability–abundance relationships across species.  
- Ensemble models outperformed single algorithms in predictive accuracy and calibration.  
- Abundance maps successfully prioritised high-density areas.  
- Robustness confirmed via sensitivity analysis across link functions and validation folds.  

## Impact
- Provided conservation managers with **high-resolution, actionable maps** to target monitoring and intervention.  
- Demonstrated that **ensemble ML** applied to presence-only data can yield reliable abundance estimates — a transferable approach for other taxa and regions.  

## Links & Resources
- 📄 **Paper:** [Ecography article](https://doi.org/10.1111/ecog.05776)  
- 💾 **Data repository:** [Dryad dataset](https://datadryad.org/dataset/doi:10.5061/dryad.0zpc866wv)  

## Role
- Led study design and workflow development.  
- Implemented ML modelling and spatial validation.  
- Created reproducible scripts, figures, and outputs.  
- Wrote manuscript and coordinated co-author contributions.  

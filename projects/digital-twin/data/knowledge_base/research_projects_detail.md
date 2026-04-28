# Research Projects — Technical Case Studies

Detailed project-level summaries of Alejandro's research work, presented as data science case studies. Each entry documents the problem, approach, technical stack, results, and conservation impact.

---

## Mechanistic Framework Linking Climate to Mammal Population Declines

**Published:** *Global Change Biology* (2025) — DOI: https://doi.org/10.1111/gcb.70215
**Type:** Flagship PhD + first-author paper

**Problem:** Climate change kills species, but the exact pathways — overheating, dehydration, reduced foraging, nutritional stress — are rarely measured directly. Understanding which mechanisms drive declines is critical for designing targeted conservation interventions, not just observing that populations are falling.

**Approach:** Integrated four independent models into a unified Bayesian framework: (1) microclimate modelling — simulated fine-scale temperature, humidity, and solar radiation at roosting habitats for ringtail possums across their range; (2) mechanistic physiological energetics — estimated species-specific thermal and hydration stress (overheating, dehydration risk, foraging time budget) from microclimate inputs using biophysical models; (3) biogeochemical pathway model — captured indirect effects by modelling how climate affects vegetation nutritional quality (foliar chemistry) and food availability; (4) Bayesian hierarchical open population model — linked physiological and nutritional covariates to demographic rates (survival and recruitment) estimated from 30 years of monitoring data, with explicit detection probability correction.

**Stack:** R, JAGS (Bayesian hierarchical modelling), biophysical energetics modelling, multi-source data integration, Bayesian uncertainty propagation

**Results:** Both ringtail possum species (*Pseudochirops archeri* and *Hemibelideus lemuroides*) experienced population collapses at lower elevations and low-nutritional sites. *P. archeri*: overheating and dehydration reduce survival; limited foraging reduces recruitment. *H. lemuroides*: primarily driven by foraging constraints (foraging time budget reduced by heat), not direct physiological stress. Species-specific mechanisms revealed — identical climatic conditions create different demographic consequences depending on species traits.

**Impact:** First framework to integrate microclimate, physiology, biogeochemistry, and population dynamics in a single Bayesian system for conservation. Results directly inform conservation strategies (habitat interventions, cooling infrastructure at vulnerable roost sites).

---

## Altitudinal Migration and Seasonal Community Breathing

**Status:** Under review, *Diversity and Distributions*
**Type:** First-author manuscript (postdoctoral work)

**Problem:** Seasonal redistribution of birds along mountain gradients (altitudinal migration) is poorly quantified in tropical systems because the movements are partial, subtle, and confounded by imperfect detection. Long-term monitoring data exist but the methods to extract clean redistribution signals from them are underdeveloped.

**Approach:** Integrated 16 years of bird count data (2000–2016) from the Australian Wet Tropics, 100+ species, 100+ rainforest sites spanning full elevational gradients. Built a hierarchical Bayesian N-mixture model to jointly estimate abundance and detection probability, isolating the seasonal redistribution signal. Defined altitudinal migration as the season × elevation interaction, using ecologically centred season encoding (−0.5 = winter, +0.5 = summer) to directly interpret uphill vs. downhill movements. Pooled data across mountains using species-level random slopes to maximise power and detect consistent migration signals. Computed derived metrics: centroid shift, range width shift, beta-diversity turnover to quantify redistribution at species and community levels.

**Stack:** JAGS (hierarchical N-mixture models with structured priors, shrinkage, multi-level random effects), R (tidyverse, data reshaping, grid expansion, visualisation), vegan + betapart (beta-diversity turnover), ggplot2 + patchwork (visualisation)

**Results:** Most species exhibit predictable seasonal redistribution — uphill in summer, downhill in winter. Individual shifts aggregate into a striking community-level breathing pattern: total bird abundance peaks in lowlands during winter and in uplands during summer. Species-specific strategies range from narrow-range specialists with limited movement to generalists tracking resources more flexibly.

**Impact:** First quantitative system-wide evidence of partial altitudinal migration in tropical rainforest birds. Establishes a generalisable Bayesian workflow for redistribution detection in long-term monitoring datasets with imperfect detection.

---

## Spatial Forecasting of Community Reshuffling Under Climate Change

**Published:** *Diversity and Distributions* (2022) — DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13514
**Type:** First-author paper (PhD)

**Problem:** As species migrate uphill under climate change at different rates, community compositions will be reshuffled — species that co-occurred may no longer overlap, and novel assemblages will form. Quantifying this at the community scale requires simulating tens of thousands of assemblages simultaneously.

**Approach:** Compiled species distribution models, thermal resistance landscape surfaces, and dispersal ability data for 47 vertebrate species. Simulated uphill shifts for 7,613 community assemblages using thermal resistance layers for movement analysis; dispersal success calculated as species-specific probability of shifting given dispersal ability and landscape structure. Computed beta-diversity dissimilarity indices to quantify community turnover resulting from heterogeneous dispersal among co-occurring species. Built high-throughput, parallelised code to run multi-spatial, multi-species forecasts at scale.

**Stack:** R (spatial analysis, parallelisation, efficient file I/O), raster/vector geospatial workflows, beta-diversity metrics (vegan), landscape connectivity analysis, reproducible scripting pipelines

**Results:** Dispersal success strongly influenced by species dispersal ability, landscape composition, and climate change scenario. Heterogeneous dispersal produced marked community disassembly along elevational gradients. Local extinction rate especially high at high elevations, indicating potential mass local extinctions of upland specialists. Identified "escalator to extinction" zones where community co-occurrence declines most severely.

**Impact:** Conservation-ready maps of reshuffling hotspots; quantified the community-level "escalator to extinction" spatial signature for Australian tropical vertebrates. Outputs used in conservation planning for the Wet Tropics bioregion.
**Data:** Dryad — https://datadryad.org/dataset/doi:10.5061/dryad.ksn02v759

---

## Bayesian Spatiotemporal Models of Climate Impacts on Rainforest Birds

**Published:** *Global Change Biology* (2023) — DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.16608
**Type:** First-author paper (PhD)

**Problem:** Detecting climate-driven population signals in noisy, long-term monitoring data is hard. Multiple climatic drivers (temperature, rainfall, heatwaves, droughts, cyclones) operate simultaneously, and their effects interact with spatial structure. Standard methods cannot separate detection artefacts from true trends.

**Approach:** Assembled 17-year bird abundance datasets across multiple sites in the Australian Wet Tropics (47 species, 2000–2016). Processed satellite imagery to quantify cyclone-induced canopy structural change as a spatially explicit covariate. Built hierarchical Bayesian spatiotemporal models in JAGS: state process modelling latent population dynamics across space and time; observation process accounting for detection probability; spatial and temporal random effects for site- and year-level heterogeneity. Entered all five climate stressors (temperature, precipitation, heatwaves, droughts, cyclones) jointly to disentangle their independent effects.

**Stack:** JAGS (Bayesian spatiotemporal models), R (data processing, spatial joins, remote sensing), satellite imagery processing (vegetation change metrics), reproducible analysis pipelines

**Results:** Strong negative effect of warming and rainfall change on upland species; lowland species showed inverse positive response. Heatwaves have a negative effect on lowland populations. Cyclones and droughts have marginal population-level effects (species-specific response unrelated to elevational gradient). Spatial heterogeneity confirmed: higher elevations show stronger climate-driven declines.

**Impact:** Provides direct mechanistic evidence of differential climate impacts across an elevational gradient. Informs targeted adaptive management for upland vs. lowland bird species in tropical montane systems.
**Data:** Dryad — https://datadryad.org/dataset/doi:10.5061/dryad.hx3ffbgjj

---

## Population Viability Forecasting for Ringtail Possums

**Published:** *Diversity and Distributions* (2022) — DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13652
**Type:** First-author paper (PhD)

**Problem:** Conservation decisions (threatened species listing, management investment) need quantified probability of extinction, not just trend direction. Standard monitoring data are affected by detection probability, which biases trend estimates if not corrected. Forecasting under climate projections requires propagating uncertainty through time honestly.

**Approach:** Collated 30 years of ringtail possum monitoring data (1992–2021) with imperfect detection. Built Bayesian hierarchical open population models in JAGS: observation process (detection component) separated from true state process (abundance/trend); prior knowledge integrated for estimation stability. Propagated fitted climate–population relationships into future forecasts (2022–2050) using projected heatwave frequency and temperature scenarios. Derived population viability metrics: extinction probability, trajectory under multiple viability thresholds (absolute and quasi-extinction).

**Stack:** JAGS (Bayesian hierarchical open population model, MCMC sampling), R (data processing, covariate development, posterior analysis, visualisation), version control and reproducible scripting

**Results:** Strong negative effect of heatwave frequency on population dynamics confirmed. Rapid and severe population decline in the last three decades quantified with credible uncertainty bounds. Forecasted probability of collapse below viability thresholds within three decades under current climate trajectories. Results directly contributed to elevated conservation listing under EPBC Act and IUCN.

**Impact:** Strengthened scientific basis for conservation policy. Demonstrated detection-corrected Bayesian forecasting as a rigorous tool for species viability assessments.
**Data:** Dryad — https://datadryad.org/dataset/doi:10.5061/dryad.m63xsj44h

---

## Predicting Species Abundance from Environmental Suitability

**Published:** *Ecography* (2021) — DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/ecog.05776
**Type:** First-author paper (PhD)

**Problem:** Conservation requires abundance maps, not just occurrence maps. Generating abundance maps traditionally requires expensive, spatially limited surveys. But 29 years of monitoring data plus modelled suitability surfaces raises a question: can we convert SDM outputs into abundance predictions?

**Approach:** Integrated large-scale presence-only occurrence data, count survey data, and high-resolution climate/topography layers for 50 endemic species. Trained a 9-algorithm SDM ensemble (SRE, CTA, Random Forest, MARS, FDA, MaxEnt, GAM, GBM, ANN) per species, generating consensus suitability surfaces. Modelled observed abundance as a flexible function of suitability (tested multiple link functions: log, logit, identity, clog-log). Spatial (blocked) cross-validation to avoid overfitting to geographically autocorrelated count data. Produced spatially explicit abundance maps with uncertainty bands.

**Stack:** R (biomod2 for SDM ensemble, data wrangling, visualisation), 9-algorithm ML/statistical ensemble, spatial cross-validation, geospatial raster processing

**Results:** Strong suitability–abundance relationships confirmed across 50 endemic species. Ensemble models outperformed single algorithms in predictive accuracy and calibration. Average 55% of deviance explained; abundance maps successfully prioritised high-density areas. Robustness confirmed via sensitivity analysis across link functions.

**Impact:** Provides conservation managers with high-resolution, actionable abundance maps from presence-only data. Demonstrates that ensemble SDM + abundance regression is a transferable approach for other taxa and regions.
**Data:** Dryad — https://datadryad.org/dataset/doi:10.5061/dryad.0zpc866wv

---

## Bird Population Trends for Conservation Listing (Shiny App)

**Published:** *PLOS One* (2021) — DOI: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0254307
**Interactive app:** https://alejandrodelafuente.shinyapps.io/BirdsPopTrendAWT/
**Type:** Co-first analytical contribution (PhD)

**Problem:** Time-series monitoring data for rainforest birds showed concerning trends, but statistical analyses had not been conducted at a scale and accessibility level that could support threatened species nominations. Policy uptake required both robust trend estimates AND interactive visualisation for non-specialist decision-makers.

**Approach:** Compiled long-term monitoring datasets; harmonised time-series counts across sites and species. Fitted Generalised Linear Models (GLMs) with time and covariates (survey effort, habitat changes) to characterise population trends per species. Identified 14 species showing significant declines or vulnerabilities. Developed a Shiny web app to visualise trends, confidence intervals, and nomination thresholds interactively for stakeholders and policymakers.

**Stack:** R (GLMs, time-series analysis, data harmonisation), Shiny (interactive dashboard deployed to shinyapps.io), ggplot2 (visualisation), GitHub (reproducible code)

**Results:** Significant declining trends detected in multiple rainforest bird species. Results directly informed 14 threatened species nominations under EPBC and IUCN frameworks. Shiny app deployed publicly, enabling transparent stakeholder engagement and policy uptake.

**Impact:** One of the most direct examples in Alejandro's work of translating statistical analysis into conservation policy outcomes. Results contributed to 14 threatened species nominations.

---

## Biogeochemical Pathway Cascades via Bayesian Hierarchical Models

**Published:** *Oecologia* (2024) — DOI: https://link.springer.com/article/10.1007/s00442-024-05630-y
**Type:** First-author paper (PhD crossover / postdoc)

**Problem:** How does herbivory fit within the broader web of ecosystem processes? Understanding herbivore–plant–nutrient interactions requires modelling an interconnected network of pathways, not single pairwise relationships.

**Approach:** Established a network of 25 field sites covering key abiotic gradients (temperature, precipitation, geology) in the Australian Wet Tropics. Built Bayesian hierarchical models specifying direct and indirect pathways: climate and geology → soil chemistry → foliar nitrogen and chemistry → insect herbivory; with random effects across geographical sites. Compared responses across three widespread rainforest tree species to identify species-specific vs. universal patterns. Implemented in R + JAGS with full uncertainty quantification.

**Stack:** R, JAGS, Bayesian hierarchical pathway models, multi-variable ecological data, field-based data collection

**Results:** Climate and geology exert overarching influence on herbivory, both directly and indirectly. Individual soil nutrients show equivocal predictive power once geological origin is accounted for. Different tree species growing under identical conditions show divergent responses.

**Impact:** Advanced understanding of ecosystem functioning by quantifying complex ecological cascades in a tropical system. Framework is transferable to other tropical ecosystems.
**Data:** Dryad — https://datadryad.org/dataset/doi:10.5061/dryad.d51c5b08s

---

## Forest Gap Effects on Tropical Bird Abundance

**Published:** *Ecologica Montenegrina* (2025) — DOI: https://doi.org/10.37828/em.2025.88.11
**Type:** Analytical contribution to collaborative study (co-author)

**Problem:** Forest gaps alter microhabitat structure and resource availability, but robust quantification of their effects on tropical bird species requires statistical methods that handle abundance gradient responses rather than simple presence/absence comparisons.

**Approach:** Collaborated with field ecologists who ran a 5-year mist-netting study (2015–2019) across paired sites (forest gaps vs. closed canopy) in Thai lower montane rainforest. Designed and implemented the analytical framework using GLMs with appropriate error structures to model species abundance as a function of gap-related covariates (gap size, canopy position, distance to edge). Controlled for site-level variability; validated models through residual diagnostics. Led statistical analysis while collaborators led field data collection.

**Stack:** R (GLMs, exploratory analysis, model validation), reproducible analytical scripts

**Results:** Total bird abundance did not differ between forest gaps and closed canopy. Strong effect of forest gaps on bird assemblage composition, not just abundance. Most species show no relationship with gap size; *Cyornis whitei* strongly prefers larger gaps. Gap sizes of 130–1,020 m² are not highly detrimental overall, but reduce abundance of sensitive species.

**Impact:** Quantified the nuanced (not simply positive or negative) effects of forest gaps on tropical birds; supports forest management decisions balancing disturbance with biodiversity outcomes.

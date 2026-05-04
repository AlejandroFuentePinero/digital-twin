# Climate-Induced Physiological Stress Drives Rainforest Mammal Population Declines

**Source:** https://doi.org/10.1111/gcb.70215
**Published:** 2025 in *Global Change Biology* (first-author).

## What it is

A first-author paper in *Global Change Biology* presenting a novel four-component integrated framework that diagnoses **causal mechanisms** of population decline in rainforest ringtail possums under climate change — moving beyond correlative climate-population relationships to identify the specific physiological and ecological pathways driving collapse. The framework is broadly applicable to other mammalian herbivores in heterogeneous landscapes.

Studied two endemic Wet Tropics species across 30 years of population monitoring (1992–2021): *Pseudochirops archeri* (green ringtail possum) and *Hemibelideus lemuroides* (lemuroid ringtail possum). The paper identifies species-specific decline mechanisms — overheating, dehydration, and foraging constraints for *P. archeri*; foraging-constraint-dominant for *H. lemuroides* — and outputs scenario-tested forecasts to guide targeted conservation intervention.

## Methods

The framework integrates four model components in a **single unified Bayesian system** implemented in R + JAGS, designed so that the components inform each other through shared posterior structure rather than running as independent analyses with hand-stitched outputs.

1. **Fine-scale microclimate modelling** of roosting conditions, generating species-specific microclimate exposure rather than coarse weather-station summaries.
2. **Mechanistic physiological energetics model** quantifying thermal stress (overheating thresholds), hydration stress (dehydration risk), and foraging time budgets — derived from species traits, not fitted to outcome.
3. **Biogeochemical pathway model** capturing indirect effects on food quality (foliar chemistry) and food availability over time — the ecological-mechanism layer.
4. **Bayesian hierarchical open population model** linking physiological and nutritional covariates to demographic rates (survival and recruitment), with explicit detection-probability correction so observation noise doesn't masquerade as population trend.

**Data:** 30 years of population monitoring across multiple survey points; species-specific microclimate; species-trait physiological parameters (overheating thresholds, dehydration tolerances, foraging time budgets); foliar chemistry and food availability time-series.

## Theoretical contribution

The structural novelty is **bridging "bottom-up" biophysical models** (trait-based, mechanistic, derived from species physiology) **with "top-down" statistical models** (occurrence/abundance, fitted to monitoring data) in a single unified framework. The standard alternative is to run them as separate analyses then qualitatively compare outputs — which loses the ability to do causal attribution because each model carries its own uncertainty estimated independently.

By integrating in one Bayesian system, the framework produces:

- **Causal attribution rather than correlation** — species-specific causal pathways from climate variability through physiological stress to demographic rate change.
- **Coherent uncertainty propagation** — uncertainty from each component flows into the joint posterior rather than being ignored or naively combined.
- **Scenario-testing capability** — counterfactual climate scenarios produce forecasts where uncertainty grows appropriately rather than artificially narrowing through naive aggregation.

Applicable beyond ringtail possums to other herbivorous mammals where physiology + nutrition + population dynamics interact — provides a methodological template, not a one-off study design.

## Results

Identified species-specific decline mechanisms with full posterior credible intervals:

- ***P. archeri*:** overheating, dehydration, and foraging-time-budget constraints jointly drive reduced survival and recruitment.
- ***H. lemuroides*:** foraging constraints emerged as the dominant driver — different mechanism, same trajectory.

Scenario forecasts under projected climate change indicate continued decline; species-specific causal attribution enables targeted intervention (e.g., microclimate refugia for *P. archeri*; food-resource conservation for *H. lemuroides*) rather than generic warming-mitigation responses. Results contribute to ongoing conservation-listing decisions for both species.

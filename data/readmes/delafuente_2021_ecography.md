# Predicting Species Abundance by Implementing the Ecological Niche Theory

**Source:** https://onlinelibrary.wiley.com/doi/full/10.1111/ecog.05776
**Published:** 2021 in *Ecography* (first-author).

## What it is

A first-author paper in *Ecography* that **systematically tests whether SDM-derived habitat suitability predicts observed local abundance** — answering a long-standing question in macroecology about whether suitability surfaces (typically used for presence/absence) can be extended to quantitative abundance prediction at fine spatial scales.

Tested against 29 years of monitoring data on 50 endemic species in the Australian Wet Tropics. Result: the suitability–abundance relationship explained on average **55% of deviance**, demonstrating SDM-based suitability surfaces are a powerful and widely applicable tool for fine-scale conservation planning when ground-truth abundance data is sparse.

## Methods

Three-stage pipeline:

1. **Multi-algorithm SDM ensemble (9 algorithms)** generating consensus suitability surfaces per species: SRE (surface range envelope), CTA (classification trees), Random Forest, MARS, FDA, MaxEnt, GAM, GBM, ANN. Ensemble approach reduces algorithm-specific bias rather than committing to any single SDM method.
2. **Suitability-vs-abundance regression** testing multiple link functions (log, logit, identity, complementary log-log) systematically rather than assuming one functional form. The link-function test addresses model-form ambiguity head-on rather than reporting whichever happens to fit best.
3. **Spatial (blocked) cross-validation** for honest predictive performance estimation. Random k-fold cross-validation overstates performance on spatially autocorrelated count data; blocked CV partitions the landscape geographically, so training and held-out folds are not adjacent.

**Data:** 29 years of abundance monitoring; 50 endemic vertebrate species; presence-only occurrence records for SDM training; high-resolution climate and topography layers.

## Theoretical contribution

Three methodological choices define the paper's rigour:

- **9-algorithm ensemble** rather than single algorithm — reduces model-specific bias, avoids a single contestable methodological choice driving downstream conclusions. The result is robust across algorithm families, not contingent on choosing the "right" SDM.
- **Spatial blocked cross-validation** rather than random k-fold — respects spatial autocorrelation in count data, which random k-fold systematically violates. Random CV would have overestimated suitability→abundance predictive skill; blocked CV gives the honest number.
- **Multiple link functions tested systematically** — addresses model-form uncertainty rather than assuming a functional form. Multiple link functions tested produces a comparison rather than a contestable single fit.

These choices are recurring methodological discipline in this research programme — separating real signal from artefact through systematic alternatives, not single best-fit choices.

## Results

- **Mean 55% deviance explained** across 50 species — substantial, varied across taxa (the species-level variation reflects genuine intrinsic differences in suitability–abundance coupling, not methodological noise).
- **First systematic large-scale test** of SDM→abundance extrapolation for tropical endemics in this region.
- Output: spatially explicit fine-scale abundance maps with uncertainty for 50 endemic species, usable for conservation prioritisation in data-sparse regions.

The result enables **fine-scale conservation planning** in places where presence/absence is the only operational data — a substantive enabling tool for tropical conservation work.

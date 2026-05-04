# Predicted Alteration of Vertebrate Communities under Climate-Induced Elevational Shifts

**Source:** https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13514
**Published:** 2022 in *Diversity and Distributions* (first-author).

## What it is

A first-author paper in *Diversity and Distributions* that simulates the **uphill dispersal** of 7,613 community assemblages of 47 vertebrate species under climate-induced elevational shifts in the Australian Wet Tropics. The paper quantifies the spatial signature of the "escalator to extinction" — community disassembly driven by *heterogeneous* dispersal success across species, even when individual species could in principle survive.

The contribution is methodological as well as ecological: it operationalises the well-known "escalator to extinction" concept into a spatially explicit, species-trait-aware simulation framework that produces inspectable per-cell community-turnover metrics rather than aggregate species counts.

## Methods

Spatially explicit dispersal simulation pipeline:

1. **Species distribution models (SDMs)** for 47 vertebrate species establishing baseline thermal niches and current distributions.
2. **Thermal resistance landscape layers** built from remote-sensing and topographic data, used as **movement friction** rather than Euclidean distance — so dispersal cost reflects realistic landscape structure (ridges, gaps, thermal mosaics) rather than straight-line distance.
3. **Per-species dispersal-ability parameters** characterising how far and how successfully each species can shift along a friction landscape.
4. **Community-level dispersal simulation** computing, per cell, the probability that each species in the local assemblage successfully shifts uphill given dispersal ability and thermal resistance.
5. **Beta-diversity dissimilarity indices** (Sørensen and Bray–Curtis) quantifying community turnover from heterogeneous per-species dispersal success — capturing community disassembly as a spatial signal, not just per-species range loss.
6. **High-throughput parallelised processing** for multi-species scenario comparison across all 7,613 assemblages.

**Data:** 47 vertebrate species presence-only occurrence data; high-resolution climate and topography layers; species-trait dispersal parameters; 7,613 community assemblages spanning the full elevational gradient.

## Theoretical contribution

Two methodological choices shape the paper's contribution:

- **Thermal resistance vs Euclidean distance for dispersal simulation.** Standard dispersal-cost models treat the landscape as a uniform medium; using thermal resistance captures the reality that some species can't traverse warm ridgelines or unsuitable microclimate corridors even when the destination is geographically close. The friction-layer formulation is reusable.
- **Community-level metrics from individual-species dispersal probabilities** rather than running each species in isolation and aggregating after. This captures the *escalator to extinction* signal — communities don't lose species uniformly; they lose the dispersal-limited subset, fundamentally restructuring assemblages even when many individual species survive.

These two together produce inspectable maps of *where* community disassembly will be most severe, rather than aggregate "X species at risk" statistics.

## Results

- Spatially explicit maps of community reshuffling intensity across the Wet Tropics.
- Predicted **mass local extinction rates strongest at high elevations** — the classic "escalator to extinction" pattern, now quantified per-cell with species-trait awareness.
- Quantified the spatial signature of heterogeneous dispersal in a tropical vertebrate community — first systematic application at this scale and trait specificity in the system.

Practical implication: conservation prioritisation should weight high-elevation refugia and dispersal corridors differently from generic warming-mitigation interventions.

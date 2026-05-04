# Relationships Between Abiotic Factors, Foliage Chemistry and Herbivory in a Tropical Montane Ecosystem

**Source:** https://link.springer.com/article/10.1007/s00442-024-05630-y
**Published:** 2024 in *Oecologia* (first-author, with Youngentob, Marsh, Krockenberger, Williams, Cernusak).

## What it is

A first-author *Oecologia* paper that traces the **causal chain from climate and geology → soil nutrients → foliar chemistry → insect herbivory** across the Australian Wet Tropics, using a hierarchical Bayesian model that lets direct and indirect (mediated) pathways be quantified jointly rather than as separate regressions. The paper tests whether resource availability — frequently used as a one-line predictor of herbivory pressure — actually predicts herbivory once the underlying geological context is accounted for.

The answer: largely no — once geological origin is controlled, individual soil nutrients become equivocal predictors of foliar composition, and **species growing under the same conditions can respond very differently**. The contribution reframes herbivore–plant interactions away from simple resource-gradient explanations toward species-specific limiting factors operating through indirect biogeochemical pathways.

## Methods

**Study system**: Australian Wet Tropics (~7,000 km²), 14–26 °C mean annual temperature, 1,200–4,000 mm annual rainfall, soils derived from basalt, rhyolite, and granite — three contrasting parent materials producing a pronounced edaphic gradient from nutrient-rich basaltic to nutrient-poor lithosols.

**Site network**: 25 plots of ~1 ha covering 94% of the bioregion's climatic variability, spanning 400–1,300 m elevation across all three soil parent materials.

**Tree species**: 3 widespread canopy species — fast-growing generalists vs slow-growing montane species from different families — selected to expose contrasting growth strategies. Includes closely related congeners to handle uneven distributional sampling when comparing growth strategies.

**Measurements**:
- **Climate covariates**: mean temperature, precipitation across each site.
- **Geology covariate**: soil parent material (basalt / rhyolite / granite).
- **Soil chemistry**: nitrogen, phosphorus, mineralisation rates, exchangeable cations.
- **Foliar chemistry**: per-species nitrogen and other nutritional indicators.
- **Herbivory damage**: per-leaf damage estimates aggregated to species × site.

**Model**: hierarchical Bayesian implementation in **R + JAGS** (via `jagsUI`), three pathways in one joint posterior:
1. Climate + geology → soil nutrient availability.
2. Soil nutrients → foliar chemistry (per species).
3. Foliage chemistry + climate → herbivory damage (per species).

Vague priors; convergence verified by R̂; posterior predictive checks paired with Bayesian p-values for fit assessment.

**Why the joint hierarchical structure**: separate regressions would estimate each link's uncertainty independently and lose the indirect effect. The joint model produces coherent uncertainty propagation across the chain — the indirect effect of geology on herbivory (via soil and foliar chemistry) is recovered as a quantified pathway coefficient with credible interval, not a hand-stitched product of separate regressions.

## Key results

- **Climate and geology jointly shape herbivory pressure**, both directly and through indirect biogeochemical pathways (soil and foliar chemistry).
- **Once geological origin is accounted for, individual soil nutrient concentrations are equivocal predictors of foliar composition** — i.e. the popular "soil → leaf → herbivore" simplification fails on closer inspection.
- **Species-specific responses to identical conditions**: the three study species respond differently to the same resource gradients, indicating that limiting factors are species-idiosyncratic rather than landscape-uniform.
- The paper reinforces a recurring finding from this research programme: simple gradients are useful framing, but **mechanism requires identifying the right limiting factor per species** rather than relying on aggregated proxies.

## Theoretical contribution

- **Hierarchical pathway model rather than separate regressions** as the right tool for ecosystem-scale causal questions. Joint posterior gives coherent uncertainty across the climate → soil → leaf → herbivore chain; separate-regression alternatives lose the indirect effect.
- **Empirical pushback on resource-availability-as-master-predictor** for herbivory. The "more resources → more herbivory" intuition does not survive species-level inspection in this system.
- **Bottom-up regulation framing** with explicit mediation: climate and geology operate as upstream regulators whose biological effects are filtered through species-specific physiological constraints rather than directly mapped from soil nutrients to leaves to insects.
- **Contributes a methodological template** to the broader research thread: the same hierarchical-modelling discipline used for population dynamics in the GCB and DDI papers is here applied to nutrient-flow and herbivory questions, demonstrating the breadth of the toolkit.

# The Climatic Drivers of Long-Term Population Changes in Rainforest Montane Birds

**Source:** https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.16608
**Published:** 2023 in *Global Change Biology* (first-author, with A. Navarro and S.E. Williams).

## What it is

A first-author *Global Change Biology* paper that **decomposes climate-change effects on rainforest bird populations into multiple distinct climatic stressors** — long-term warming, long-term rainfall change, extreme heatwaves, intense droughts, and tropical-cyclone-induced canopy structural damage — and quantifies each driver's effect across the elevational gradient of the Australian Wet Tropics. Where most studies treat "climate change" as a single covariate, this paper separates its components and shows they have divergent, sometimes opposite, effects on different elevational communities.

Sister paper to *Williams & de la Fuente (2021, PLOS One)* — that paper documented the empirical pattern of bird redistribution; this one identifies the climatic *mechanisms* driving it.

## Methods

Bayesian N-mixture hierarchical model in R + JAGS, separating the ecological state process from the observation (detection) process so observation noise doesn't bias trend estimation.

**Data**:
- Bird monitoring 2000–2016 across **124 survey locations in 24 sites** spanning four mountain ranges (Spec, Atherton, Carbine, Windsor uplands). 1,977 samples in 495 surveys.
- 47 species with sufficient temporal coverage (filtered from 54 monitored).
- Elevational stratification: lowland (0–300 m), midland (300–900 m), upland (>900 m).

**Climate predictors** (1965–2019 daily climatology, 0.05° / ~5 km grid; validated to 96–99% correlation against weather stations):
- **Long-term mean temperature** — 25-year window average.
- **Long-term mean precipitation** — 25-year window average.
- **Extreme heatwaves** — area under curve above the 97.5th-percentile daily maximum temperature threshold (>35°C), capturing intensity × duration.
- **Intense droughts** — analogous AUC below the 2.5th-percentile monthly precipitation threshold (<10 mm).
- **NDVI from Landsat 5 TM and Landsat 8 OLI/TIRS** (1987–2021, 30 m pixels with 1 km buffer per site, annual median composites) — captures cyclone-induced canopy structural change rather than just storm-track proximity.

Short-term events entered with 1-year lag. Bayesian fit: 3 parallel chains, 200,000 iterations each, 50% burn-in, thinning 1-in-100 → 3,000 posterior samples; convergence verified by R̂ < 1.1; Bayesian p-value 0.47 ± 0.036.

## Key results

- **Climate has changed measurably**: regional mean temperature rose 0.013 ± 0.002 °C/yr, with lowland heatwaves intensifying faster (0.23 ± 0.07 °C/yr) than uplands (0.07 ± 0.02 °C/yr).
- **Long-term warming is the dominant driver**: 72% of species show a significant temperature response. Highly **asymmetric across elevation** — lowland species *benefit* from warming (positive effect, expansion); upland-restricted species show inverse strong negative response (range contraction, decline).
- **Long-term precipitation change** drives a parallel asymmetric pattern: lowlands respond positively to increasing rainfall, uplands negatively, consistent with productivity–precipitation relationships in tropical mountain forests.
- **Extreme heatwaves** have a *negative* effect on lowland populations despite the positive long-term warming response — i.e. the same community can benefit from gradual warming and be punished by extreme events.
- **Cyclones (NDVI-derived) and droughts** have only marginal community-level effects, with high inter-species variability.

## Theoretical contribution

- **Multi-stressor decomposition framework**. Separating long-term climate change from extreme-event climate change in a single hierarchical model lets the paper pin which mechanism affects which community — a level of resolution most regional climate-and-biodiversity studies do not deliver.
- **Detection-corrected long-term abundance modelling** as standard discipline. The same observation-vs-state separation that recurs across this research programme (DDI 2022, GCB 2025).
- **NDVI as cyclone-effect proxy** rather than wind-track distance — captures the actual ecological impact (canopy structural damage and recovery) rather than a meteorological abstraction.
- **Quantitative grounding for the "escalator to extinction"**. Williams & de la Fuente (2021) showed the redistribution; this paper identifies *which climate dimensions cause it*. Targeted conservation depends on knowing whether to mitigate gradual warming, extreme events, drought, or canopy damage.

The paper underwrites the conservation-listing work emerging from the Wet Tropics monitoring programme by giving managers driver-specific evidence.

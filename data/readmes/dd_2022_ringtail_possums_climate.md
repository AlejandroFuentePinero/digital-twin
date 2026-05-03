# Climate Change Threatens the Future of Rainforest Ringtail Possums by 2050

**Source:** https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13652
**Citation:** de la Fuente A. & Williams S. (2022). *Diversity and Distributions* 28, 1180–1190. First-author.

## What it is

A first-author paper in *Diversity and Distributions* that uses 30 years of monitoring data (1992–2021) and Bayesian hierarchical population models to forecast the probability of rainforest ringtail possum population collapse by 2050 under projected warming and heatwave scenarios. The paper identifies extreme heatwaves (not mean warming) as the primary demographic driver and outputs decision-grade results that directly supported elevated conservation status under Australian threatened-species legislation (EPBC Act).

This is the predecessor work to the GCB 2025 mechanistic-framework paper — *DDI 2022* establishes the **demographic forecasting** layer; *GCB 2025* adds the mechanistic causal-pathway layer.

## Methods

Bayesian hierarchical open population model in **R + JAGS** with explicit separation of state and observation processes:

1. **State process** — true latent abundance and underlying trend over time, modelled as a function of climate covariates.
2. **Observation process** — imperfect detection probability modelled separately so observation noise doesn't bias trend estimation. Detection probability has its own covariates (survey conditions, observer effort).
3. **Forward projection** — fitted historical climate–population relationships propagated forward 2022–2050 under projected heatwave-frequency and warming scenarios. Full posterior propagation through the forecast horizon, not point estimates.
4. **Population viability analysis (PVA)** — probability of falling below absolute and quasi-extinction thresholds calculated under multiple viability definitions, producing a probabilistic risk surface rather than a single number.

**Data:** 30-year monitoring dataset (1992–2021) across multiple survey points in the Australian Wet Tropics; observed temperature and heatwave frequency time-series; downscaled climate projections to 2050.

## Theoretical contribution

The methodological emphasis is on **rigour appropriate to a decision-support output**:

- **Explicit detection-probability correction** prevents underestimating decline. A naive trend on raw counts treats fewer detections as fewer animals; the state-space approach distinguishes "harder to detect" from "fewer present." This is the same discipline that recurs in transferable form in the AI work — separating the observation process from the state process.
- **Full posterior propagation through the forecast** rather than point estimates. Uncertainty grows over the projection window as it should — the credible interval at 2050 is wider than at 2022 — making the forecast honest about what it doesn't know.
- **PVA over multiple viability thresholds** rather than a single cutoff, giving conservation managers a risk surface they can interpret against their own decision criteria rather than a single contestable number.

## Results

Probability of falling below viability thresholds by 2050 was high under projected scenarios. **Heatwave frequency** — not mean warming — emerged as the primary demographic driver, identifying extreme events rather than gradual change as the actionable mechanism.

Results were used directly to support threatened-species re-listing for the studied species under Australia's Environment Protection and Biodiversity Conservation Act (EPBC Act). Cited as part of the 15-rainforest-species conservation-listing nomination work that came out of this research thread.

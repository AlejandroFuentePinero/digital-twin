# Publications

Full list: https://scholar.google.com.au/citations?user=7CKVdZwAAAAJ&hl=en
ORCID: https://orcid.org/0000-0001-9686-3844
All papers downloadable from portfolio: https://alejandrofuentepinero.github.io/academic/
All open-access datasets: https://datadryad.org/search?q=0000-0001-9686-3844

---

## First-author peer-reviewed papers

### Mountains magnify mechanisms in climate change biology
**de la Fuente A., Chen IC., Briscoe N.J., et al. (2026)**
*Nature Climate Change* 16, 115–117
DOI: https://doi.org/10.1038/s41558-025-02549-x
**Lay summary:** Mountains, with their sharp climatic contrasts, are iconic examples of climate-driven species movement and loss. We argue these same contrasts make mountains powerful natural laboratories for discovering the mechanisms behind biological change — making them uniquely valuable for understanding climate impacts globally.
**Technical summary:** Perspective/commentary piece synthesising comparative mountain biology literature. Core argument: the compressed climatic gradients of mountain elevations act as natural experiments, allowing causal mechanisms of biological change to be detected and quantified with greater power than lowland systems. Contribution is theoretical framework and synthesis of existing evidence, not new empirical data. Identifies key research directions for leveraging mountain systems in climate biology.

---

### Climate-Induced Physiological Stress Drives Rainforest Mammal Population Declines
**de la Fuente A., Briscoe N.J., Kearney M.R., Williams S.E., Youngentob K.N., Marsh K.J., Cernusak L.A., Leahy L., Larson J., Krockenberger A.K. (2025)**
*Global Change Biology* 31: e70215
DOI: https://doi.org/10.1111/gcb.70215
**Lay summary:** We built a novel mechanistic framework integrating biophysical, nutritional, and population models to show how climate change is causing ringtail possum population collapses in the Australian Wet Tropics. For *Pseudochirops archeri*, overheating, dehydration, and limited foraging drive reduced survival and recruitment. For *Hemibelideus lemuroides*, foraging constraints are the primary driver. The framework is broadly applicable to other mammalian herbivores.
**Technical summary:** Data: 30 years of ringtail possum population monitoring (1992–2021), species-specific microclimate data, mechanistic physiological energetics (overheating and dehydration thresholds, foraging time budgets), nutritional quality data (foliar chemistry, food availability). Methods: Four-component framework integrated in a unified Bayesian system implemented in R + JAGS — (1) fine-scale microclimate modelling of roosting conditions, (2) mechanistic physiological energetics model quantifying thermal and hydration stress, (3) biogeochemical pathway model capturing indirect effects on food quality and availability, (4) Bayesian hierarchical open population model linking physiological/nutritional covariates to demographic rates (survival and recruitment) with explicit detection probability correction. Key technical decision: bridges "bottom-up" biophysical (trait-based) models and "top-down" statistical (occurrence/abundance) models in a single unified framework, enabling causal attribution rather than correlation. Output: species-specific causal pathways from climate variability to demographic decline; scenario-tested forecasts to guide targeted conservation interventions.

---

### Relationships between abiotic factors, foliage chemistry and herbivory in a tropical montane ecosystem
**de la Fuente A., Youngentob K.N., Marsh K.J., Krockenberger A.K., Williams S.E., Cernusak L.A. (2024)**
*Oecologia*
DOI: https://link.springer.com/article/10.1007/s00442-024-05630-y
**Lay summary:** We investigated how climate, geology, soil nutrients, and foliage chemistry interact to shape insect herbivory across 25 sites in the Australian Wet Tropics. Climate and geology exert an overarching influence on herbivory both directly and indirectly, but different tree species growing under the same conditions can respond very differently — highlighting the importance of identifying specific limiting factors rather than relying on simple proxies.
**Technical summary:** Data: 25 field sites covering key abiotic gradients (temperature, precipitation, geology), multi-source measurements of soil nutrient availability (nitrogen, phosphorus, mineralisation rates), foliar chemistry for 3 widespread rainforest tree species, and insect herbivory damage estimates. Methods: Bayesian hierarchical models specifying direct and indirect pathways — climate and geology → soil chemistry → foliar nitrogen/chemistry → herbivory — with site-level random effects capturing spatial nesting. Implemented in R and JAGS. Key technical decision: hierarchical pathway structure rather than separate regressions, enabling simultaneous quantification of direct and mediated (indirect) effect strengths. Output: posterior estimates of pathway coefficients; evidence that individual soil nutrients are equivocal predictors once geological origin is accounted for; species-specific response variation identified as a key ecological finding.

---

### The climatic drivers of long-term population changes in rainforest montane birds
**de la Fuente A., Navarro A., Williams S. (2023)**
*Global Change Biology* 00, 1–9
DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.16608
**Lay summary:** Using hierarchical population models on 17 years of bird monitoring (47 species), we disentangled the effects of temperature, precipitation, heatwaves, droughts, and cyclones on rainforest bird populations across elevational gradients. Warming and rainfall changes strongly affected bird communities, with upland species declining sharply while lowland species increased. Heatwaves had a negative effect on lowland populations; cyclones and droughts had marginal effects.
**Technical summary:** Data: 17-year bird monitoring dataset (2000–2016), 47 species, spatiotemporal climate predictors (temperature, precipitation, heatwave indices, drought metrics, cyclone exposure), satellite imagery processed to quantify cyclone-induced canopy structural change. Methods: Bayesian hierarchical spatiotemporal models in JAGS — state process modelling latent population abundance dynamics across space and time, observation process accounting for imperfect detection probability, spatial and temporal random effects for site- and year-level heterogeneity. All five climatic stressors entered jointly. Key technical decision: separating detection probability from true abundance is essential for unbiased trend estimation in long-term monitoring data; satellite imagery-derived structural damage used as a cyclone covariate captures species-level canopy responses rather than just storm track proximity. Output: effect sizes with credible intervals for each climatic driver, stratified by elevation; upland specialist decline confirmed, marginal cyclone and drought effects confirmed.

---

### Climate change threatens the future of rain forest ringtail possums by 2050
**de la Fuente A. & Williams S. (2022)**
*Diversity and Distributions* 00, 1–11
DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13652
**Lay summary:** Using Bayesian hierarchical population models on 30 years of monitoring data (1992–2021), we forecasted that extreme heatwaves and warming will drive rainforest ringtail possums below viability thresholds by 2050. Results directly supported elevated conservation status for these species.
**Technical summary:** Data: 30-year ringtail possum monitoring dataset (1992–2021, multiple survey points), temperature and heatwave frequency time-series (observed and projected). Methods: Bayesian hierarchical open population model in JAGS separating state process (true abundance and underlying trend) from observation process (imperfect detection probability); model fitted over historical period, then projected forward 2022–2050 by propagating fitted climate–population relationships under projected heatwave and warming scenarios; population viability analysis calculating probability of absolute and quasi-extinction under multiple viability thresholds. Key technical decision: explicit detection probability correction to prevent underestimation of population decline; full posterior propagation through forecast rather than point estimates, so uncertainty grows appropriately over time. Output: probability of collapse below viability thresholds by 2050; heatwave frequency identified as primary driver; results used directly to support threatened species re-listing under EPBC Act.

---

### Predicted alteration of vertebrate communities in response to climate-induced elevational shifts
**de la Fuente A., Krockenberger A., Hirsch B., Cernusak L., Williams S. (2022)**
*Diversity and Distributions* 28, 1180–1190
DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/ddi.13514
**Lay summary:** We simulated the uphill dispersal of 7,613 community assemblages under climate-induced elevational shifts, using thermal resistance layers for 47 vertebrate species. Dispersal success depended strongly on species dispersal ability and landscape structure. Heterogeneous dispersal produced severe community disassembly at high elevations — a classic "escalator to extinction" pattern.
**Technical summary:** Data: species distribution models for 47 vertebrate species, thermal resistance landscape layers (derived from remote sensing and topographic data), per-species dispersal ability parameters, 7,613 community assemblages across the full elevational gradient. Methods: spatially explicit dispersal simulation using thermal resistance as a movement friction layer; dispersal success calculated as species-specific probability of successfully shifting given dispersal ability and landscape structure; beta-diversity dissimilarity indices (Sørensen and Bray–Curtis) quantifying community turnover from heterogeneous dispersal success; high-throughput parallelised processing for multi-species scenario comparison. Key technical decision: thermal resistance rather than Euclidean distance for dispersal simulation captures realistic landscape-scale barriers; computing community-level metrics from individual-species dispersal probabilities rather than simulating each species in isolation. Output: spatially explicit maps of community reshuffling intensity; predicted mass local extinction rates strongest at high elevations; quantified "escalator to extinction" spatial signature in a tropical vertebrate community.

---

### Predicting species abundance by implementing the ecological niche theory
**de la Fuente A., Hirsch B., Cernusak L., Williams S. (2021)**
*Ecography* 44, 1723–1730
DOI: https://onlinelibrary.wiley.com/doi/full/10.1111/ecog.05776
**Lay summary:** We showed that habitat suitability from species distribution models (SDMs) can accurately predict local species abundance at fine spatial scales. For 50 endemic species in the Australian Wet Tropics across 29 years of monitoring, the abundance–suitability relationship explained on average 55% of deviance — demonstrating a powerful and widely applicable tool for conservation planning.
**Technical summary:** Data: 29 years of abundance monitoring data, 50 endemic species, presence-only occurrence data, high-resolution climate and topography layers for model training. Methods: multi-algorithm SDM ensemble (9 algorithms: SRE, CTA, Random Forest, MARS, FDA, MaxEnt, GAM, GBM, ANN) generating consensus suitability surfaces per species; regression of suitability surfaces against observed count data testing multiple link functions (log, logit, identity, clog-log); spatial (blocked) cross-validation to respect geographic autocorrelation. Key technical decision: 9-algorithm ensemble rather than single algorithm to reduce model-specific bias; spatial cross-validation (rather than random k-fold) prevents overfitting to spatially autocorrelated count data; multiple link functions tested systematically rather than assuming one functional form. Output: mean 55% deviance explained across taxa (range across species substantial, reflecting intrinsic variation in suitability–abundance coupling); spatially explicit fine-scale abundance maps with uncertainty; first systematic large-scale test of SDM→abundance extrapolation for tropical endemics.

---

### Biomass, seed production and phenology of Chusquea montana after a massive and synchronous flowering event in Puyehue National Park, Chile
**de la Fuente A. & Pacheco N. (2017)**
*Bosque* 38(3): 599–604
DOI: https://www.scielo.cl/scielo.php?pid=S0717-92002017000300018&script=sci_arttext
**Lay summary:** First description of a synchronous flowering and seeding event of Chusquea montana bamboo in Puyehue National Park. Documented biomass, seed production, viability, and phenological stages of this rare ecological event.
**Technical summary:** Data: 8 field plots and 20 seed collection boxes in Puyehue National Park (Chile), spring 2015 flowering event in an Antillanca Nothofagus forest. Methods: plot-based above-ground biomass sampling (fresh and dry weight); temporal seed trap monitoring for production rate and viability; phenological stage classification through repeated field observations. Key technical decision: combining biomass sampling with temporal seed monitoring to capture both structural and reproductive aspects of the masting event simultaneously. Output: 33.50 Mg ha⁻¹ fresh biomass (17.66 Mg ha⁻¹ dry); 146.86 × 10⁶ seeds ha⁻¹ at peak production; 87.5% seed viability; first species-level phenological description for *Chusquea montana* in Chile.

---

## Under Review

### Altitudinal migration and seasonal redistribution in rainforest bird communities
**de la Fuente A., et al. (under review)**
*Diversity and Distributions*
**Summary:** First quantitative system-wide evidence of partial altitudinal migration in tropical rainforest birds. Hierarchical Bayesian N-mixture models applied to 16 years of monitoring data (2000–2016, 100+ species, 100+ rainforest sites across full elevational gradients). Altitudinal migration defined as the season × elevation interaction in a joint abundance-detection model. Key finding: a clear community-level "breathing" pattern — total bird abundance peaks in lowlands during winter and in uplands during summer, driven by predictable seasonal redistribution in most species. Establishes a generalisable Bayesian workflow for detecting redistribution signals in long-term imperfect-detection datasets.

---

## Co-authored peer-reviewed papers

### Long-term changes in populations of rainforest birds in the Australia Wet Tropics bioregion: A climate-driven biodiversity emergency
**Williams S. & de la Fuente A. (2021)**
*PLOS One* 16(12): e0254307
DOI: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0254307
**Lay summary:** 17 years of bird monitoring across 114 sites from sea level to 1,500 m showed most mid and high elevation species lost >40% of abundance at lower elevational edges, while lowland species expanded by up to 190% upward. Upland endemics declined by almost 50%. The Outstanding Universal Value of the Wet Tropics World Heritage Area is rapidly degrading.

### The effect of forest gap dynamics on tropical rainforest birds
**Siri S., Ponpithuk Y., Safoowong M., Marod D., de la Fuente A., Williams S.E., Duengkae P. (2025)**
*Ecologica Montenegrina* 88, 164–185
DOI: https://doi.org/10.37828/em.2025.88.11
**Lay summary:** 5-year mist-netting study in Thai lower montane rainforest. Forest gaps affected bird assemblages but not total abundance. Moderate gap sizes are not highly detrimental, yet can reduce abundance of sensitive species. Gaps may also promote biodiversity through niche differentiation.
**Technical role:** Designed and implemented the statistical analytical framework (GLMs for abundance–gap gradient relationships); contributed to analytical interpretation and manuscript preparation.

### New records of Lagidium cf. L. wolffsohni (Thomas, 1907) (Rodentia, Chinchillidae) in southern Chile
**Iriarte A., Rau A., de la Fuente A. (2021)**
*Notas sobre Mamíferos Sudamericanos* 3: e21.12.2
URL: https://ojs.sarem.org.ar/index.php/nms/article/view/771/98
**Lay summary:** Photographic records document the potential presence of Wolffsohn's viscacha in Puyehue National Park and Huinay, expanding the species' known northern distribution by 722 km.

### Seasonal variation in the richness, relative frequency and diversity of birds in urban wetlands of Llanquihue, southern Chile
**Gallardo J., Rau J., de la Fuente A., Marinkovic F., Teutsch C. (2018)**
*Revista Chilena de Ornitologia* 24(1): 27–36
Download: https://github.com/AlejandroFuentePinero/alejandrofuentepinero.github.io/blob/master/files/Gallardo.et.al.2018.pdf
**Lay summary:** Documented 50 bird species across three urban wetlands in Llanquihue; high diversity maintained year-round despite urbanisation. Highest richness in spring, lowest in autumn.

---

## Book Chapters

14 species accounts in *The Action Plan for Australian Birds 2020* (CSIRO Publishing, Melbourne). Species include Grey-headed Robin, Victoria's Riflebird, Wet Tropics Eastern Whipbird, Tooth-billed Bowerbird, Golden Bowerbird, Fernwren, Mountain Thornbill, Atherton Scrubwren, Bower Shrike-Thrush, Wet Tropics King-Parrot, Wet Tropics Large-Billed Scrubwren, Mountain Thornbill, Little Treecreeper, and others. Authors: Williams S.E., de la Fuente A., et al.

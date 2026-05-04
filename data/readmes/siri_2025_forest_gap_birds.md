# The Effect of Forest Gap Dynamics on Tropical Rainforest Birds

**Source:** https://doi.org/10.37828/em.2025.88.11
**Published:** 2025 in *Ecologica Montenegrina* (co-author; Siri et al., with de la Fuente as analytical-framework lead).

## What it is

A co-authored *Ecologica Montenegrina* paper examining how natural canopy gaps shape bird abundance, community composition, and seasonal dynamics in a Thai lower-montane rainforest. Five-year mist-netting study (2015–2019) in a permanent 16-ha plot, comparing paired forest-gap and closed-canopy sites at species, community, and gap-size resolution.

Alejandro's role: **designed and implemented the statistical analytical framework** — generalised linear mixed-effects models (GLMMs) for abundance–gap-gradient relationships, multivariate community ordination, and seasonal-pattern decomposition — and contributed to interpretation and manuscript preparation. The study extends Alejandro's research network beyond Australia into Southeast Asian tropical forest ecology, demonstrating reusability of the modelling toolkit (hierarchical abundance models, detection-aware analyses) outside the Wet Tropics study system.

## Methods

**Field design**:
- **5-year mist-netting study** (2015–2019) in a 16-ha permanent plot in lower-montane rainforest, Doi Chiang Dao, Thailand.
- Paired sites: 12 forest-gap sites + 12 under-closed-canopy sites.
- **1,148 captures of 81 species** total — substantive long-term sample.
- Gap sizes spanning **130–1,020 m²**.

**Statistical framework**:
- **Wilcoxon Rank Sum Tests** comparing species-level abundance between forest-gap and closed-canopy sites in dry vs wet seasons.
- **Principal Component Analysis (PCA)** on community assemblage structure across the 24 sites and across seasons — captures multivariate community-level differences.
- **Generalised Linear Mixed-effects Models (GLMMs)**, Poisson family, fitted with `lme4::glmer` in R, with month as a random effect — model individual species' abundance against forest-gap presence and seasonal covariates.
- **ANOVA on gap-size effects** across the 130–1,020 m² range to test whether gap *size* (not just gap presence) explains abundance variation.
- **Pearson correlation** between PCA assemblage scores and gap size for community-level gap-size effects.

## Key results

- **Total bird abundance does not differ between forest gaps and closed canopy** at the community level — i.e. the assemblage shifts composition rather than total numbers.
- **Forest gaps strongly affect bird community structure**: PCA separates gap-vs-canopy assemblages, especially in the dry season when seasonal migrants amplify variability.
- **Hill Blue Flycatcher (*Cyornis whitei*)** shows a strong positive gap-size response (β=0.35, z=2.57, p=0.01) — a clear gap-specialist.
- **Most species show no significant gap-size effect**, indicating gaps in the 130–1,020 m² range are *not* highly detrimental but still reduce abundance for sensitive species.
- **Seasonality dominates community variation**: 27% of the assemblage is seasonally migratory; dry-season variance (12.30) is markedly higher than wet-season variance (0.78), producing a more complex dry-season community.

## Theoretical contribution

- **Empirical refinement of the intermediate-disturbance hypothesis** in tropical Asian forests: moderate gaps are not catastrophic but modulate community composition through niche differentiation rather than total-abundance reduction.
- **Long-term mist-netting design** (5 years, paired-site, seasonal replication) provides exactly the kind of dataset where naive cross-sectional analysis fails — detection probability, seasonal turnover, and inter-annual variability all matter.
- **Methodological reuse**: the GLMM + multivariate-ordination toolkit transfers cleanly from the Wet Tropics monitoring programme (where it was developed for elevational-gradient bird community questions) to Thai montane forests with different community composition and disturbance regime. Demonstrates portability of the analytical framework.
- **Bridges Australian and Thai rainforest research networks** — co-authored with Maejo University and Kasetsart University researchers, contributing the analytical-modelling component to a field-design-led study.

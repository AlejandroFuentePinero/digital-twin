---
permalink: /
title: ""
classes: wide hide-page-title
layout: archive
excerpt: "About me"
author_profile: true
redirect_from: 
  - /about/
  - /about.html
---

# Welcome!

## Hi, I'm Alejandro — AI Engineer & Data Scientist

I've spent years trying to understand how wildlife populations respond to a changing climate: building Bayesian models on decades of field data, forecasting species viability under uncertainty, and producing evidence that fed directly into conservation decisions. Some of that work meant tracking pumas and jaguars across remote South American landscapes. Some of it meant climbing tropical mountains in the rainforests of northeast Australia to understand how global warming is quietly reshaping the lives of arboreal marsupials and song birds in the canopy above. When your model output determines whether a species gets protected, you develop a particular relationship with getting it right.

These days I work at the intersection of AI engineering and data science, building systems that turn messy real-world data into outputs people can act on. I'm particularly drawn to problems where the data is hard, the uncertainty is real, and the answer actually matters. Same instincts, different problems.

---

## What I build

End-to-end AI and data systems that prioritise reliability and usability:

- **RAG systems and LLM applications**: retrieval pipelines with evaluation frameworks (MRR, nDCG, LLM-as-judge) and structured output patterns
- **Fine-tuned models**: supervised fine-tuning of frontier models via API and QLoRA fine-tuning of open-source LLMs for domain-specific tasks, with dataset curation, training runs tracked in W&B, and benchmarked against baseline models
- **ML workflows**: from problem framing and feature engineering to model evaluation with transparent trade-offs
- **Data pipelines**: clean, testable, reproducible pipelines with validation and clear artefacts
- **Decision support**: results communicated clearly: what changed, why it matters, what to do next

---

## Featured work
<div class="ds-feature">
  <!-- Left: text -->
  <div class="ds-feature-text">
    <p>
      <strong>Job Intelligence Engine</strong>: an end-to-end job recommender and market intelligence system built on 6,100+ real job postings. Surfaces where you stand in the market, which roles fit now, and exactly what to learn next to close the gap.
    </p>
    <ul>
      <li>Skill demand and salary signals across roles and job families</li>
      <li>Best-now vs stretch recommendations with explicit rationale</li>
      <li>Upskilling priorities ranked by expected positioning lift</li>
    </ul>
    <p style="margin-top:0.5rem; font-size:0.95rem;">
      <strong>Stack:</strong> Python • SBERT embeddings • XGBoost • LightGBM • SHAP • Streamlit
    </p>
    <a class="btn btn--primary" href="/datascience/projects/job_intelligence_engine/">See demo & details</a>
  </div>

<!-- Right: image (clickable) -->
<div class="ds-feature-media">
  <a href="/datascience/projects/job_intelligence_engine/" aria-label="Open Job Intelligence Engine">
    <img
      src="https://raw.githubusercontent.com/AlejandroFuentePinero/alejandrofuentepinero.github.io/master/files/engine_path.png"
      alt="Job Intelligence Engine workflow"
    >
  </a>
</div>

<style>
  /* Featured work 2-column layout (homepage) */
  .ds-feature {
    display: grid;
    grid-template-columns: 1fr 1.15fr; /* image column slightly wider */
    gap: 28px;
    align-items: start;
    margin-top: 0.75rem;
  }

  .ds-feature-text p { margin-top: 0; }
  .ds-feature-text ul { margin: 0 0 1rem 1.1rem; padding: 0; }

  .ds-feature-media img {
    width: 100%;
    height: auto;
    display: block;
    max-height: 420px;   /* bigger */
    object-fit: cover;   /* fills space better */
    border-radius: 12px; /* optional, looks nicer */
  }

  @media (max-width: 1100px) {
    .ds-feature { grid-template-columns: 1fr; }
    .ds-feature-media img { max-height: 520px; }
  }
</style>





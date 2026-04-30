---
title: "AI-JIE: LLM Extraction & Evaluation Pipeline"
excerpt: "An async LLM pipeline that extracts structured job intelligence from raw postings using GPT-4o-mini, chain-of-thought prompt architecture, and a rigorous LLM-as-judge evaluation framework — built as the AI layer for the Job Intelligence Engine."
date: 2026-04-09
tier: featured
order: 2
---

## Links (start here)
- **GitHub repo:** [AI-JIE](https://github.com/AlejandroFuentePinero/ai-jie)
- **Published dataset:** [HuggingFace Hub — preprocessed](https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-preprocessed) · [postprocessed](https://huggingface.co/datasets/Alejandrofupi/ai-jie-jobs-lite-postprocessed)
- **Technical report:** [Architecture & evaluation methodology](https://github.com/AlejandroFuentePinero/ai-jie/blob/main/docs/technical_report.md)
- **Downstream system:** [Job Intelligence Engine](https://github.com/AlejandroFuentePinero/job-intelligence-engine)

## Overview

Raw job postings are unstructured, inconsistent, and full of ambiguity — the same skill can appear as a hard requirement in one posting and a nice-to-have in another, buried in different language each time. Traditional NLP extraction misses intent entirely.

**AI-JIE** is a structured extraction pipeline that uses an LLM to read raw postings and produce validated, intent-classified `Job` objects at scale. The core challenge was not getting the LLM to extract skills — it was getting it to reliably distinguish **required** from **preferred** from **soft** skills, and to separate genuine skill demands from responsibilities described as skills. Solving this required 33 prompt iterations and an architectural shift from flat extraction to chain-of-thought scaffolding.

## What it produces

Each posting is parsed into a Pydantic-validated `Job` object containing skills partitioned by intent (required, preferred, soft), role metadata (seniority, job family, experience, education, responsibilities), and chain-of-thought intermediate fields that enforce an extract-then-classify reasoning architecture. The published dataset covers 3,892 Data Scientist postings.

## Key engineering decisions

**Chain-of-thought scaffolding over flat extraction.** Early prompt versions asked the model to directly classify skills into required/preferred/soft. Accuracy on preferred skills was poor — the model conflated responsibilities with requirements. The solution was adding intermediate Pydantic fields (`responsibility_skills_found`, `preferred_signals_found`, `all_technical_skills`) that force the model to reason explicitly before classifying. This single architectural change was the largest accuracy gain across all 33 prompt versions.

**Two-model cost optimisation.** GPT-4o-mini handles high-volume extraction (3,892 postings); GPT-4o serves as the independent judge for evaluation. This separates the cost profile: extraction runs cheaply at scale while evaluation maintains rigour on a fixed 50-posting sample.

**Async concurrency with checkpointing.** The batch pipeline processes postings asynchronously with fault-tolerant checkpointing to JSONL — if interrupted, it resumes from the last checkpoint rather than re-extracting. This was essential for managing API costs and reliability across long batch runs.

**Deterministic postprocessing layer.** A rule-based cleanup stage applies responsibility exclusion and blocklist filtering after LLM extraction. This separates concerns: the LLM extracts broadly (deliberately over-inclusive to avoid missing skills), and the deterministic layer handles known noise patterns reproducibly.

## Evaluation framework

The pipeline includes a full evaluation system: an LLM-as-judge that scores extractions on a 1–3 scale across multiple dimensions, a human evaluation interface for calibration, Cohen's kappa for inter-rater agreement, trend tracking across prompt versions, and a HuggingFace Hub dataset pipeline for reproducible eval sets.

Human evaluation of 28 postings (1–5 scale) showed structural fields at near-perfect accuracy (seniority: 5.00, responsibilities: 5.00) with the main remaining noise in `skills_required` (4.00) handled by the postprocessing layer. Overall: **4.11/5.00**.

## Stack

Python · OpenAI API (GPT-4o-mini, GPT-4o) · instructor · Pydantic · asyncio · HuggingFace Hub · pytest

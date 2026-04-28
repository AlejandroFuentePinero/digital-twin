---
title: "MLB Analytics with SQL"
excerpt: "End-to-end SQL analytics project using the Lahman Baseball Database. Designed a complete relational workflow with schema creation, reusable views, advanced CTEs, window functions, and business-focused analyses on talent pipelines, salary dynamics, and player careers."
date: 2025-11-24
tier: featured   # featured | learning | research
order: 4
---

## Problem

The Lahman Database (1871–2024) contains 150 years of MLB data across players, salaries, teams, universities, and post-season results. The goal: build a production-quality SQL analytics workflow to answer four business-focused questions using a clean, reproducible relational schema.

## Approach

Four analytical pillars, each answered with modular SQL and visualised in Python:

1. **Talent Pipelines** — which colleges produce the most MLB players, and how has that shifted by decade?
2. **Salary & Payroll Dynamics** — team spending patterns, cumulative milestones, and decade-level comparisons.
3. **Player Career Analysis** — career length, debut/retirement windows, age distributions, and team loyalty.
4. **Player Profiles** — height/weight trends, cross-era comparisons, and physical attributes of standout players.

Built reusable analytical views to avoid repeated logic, and a Python notebook to turn SQL outputs into interpretable charts.

## What it found

Low-payroll teams that consistently outperformed expectations, decade-level shifts in college talent pipelines, and clear physical attribute differences between Hall of Fame and non-HOF career trajectories.

## SQL highlights

Window functions (RANK, NTILE, cumulative SUM), multi-step CTE pipelines, statistical SQL (COVAR_POP / VAR_POP for trend estimation), date manipulation, NULL-aware profiling, and reusable view architecture.

## Stack

PostgreSQL · Python · pandas · matplotlib · seaborn · Git/GitHub

## Links & Resources

- **GitHub Repository:** [MLB Analytics SQL Project](https://github.com/AlejandroFuentePinero/MLB_Analytics_Project)

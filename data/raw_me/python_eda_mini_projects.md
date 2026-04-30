---
title: "Exploratory Data Analysis (EDA) Projects in Python"
excerpt: "Developed an applied EDA framework combining real-world case studies — emergency call records and financial time series — to demonstrate data wrangling, feature extraction, and visualisation workflows using pandas, seaborn, and plotly."
date: 2025-10-02
tier: learning   # featured | learning | research
order: 4
---

## Problem
Data scientists often encounter diverse datasets requiring tailored cleaning, transformation, and exploratory techniques before modelling.  
**Goal:** Build a reproducible Python EDA framework demonstrating how to extract insights, engineer features, and communicate patterns from unstructured datasets across different domains — public safety (911 calls) and financial markets.

## Approach
- Designed two **end-to-end EDA pipelines** using real-world datasets:
  1. **911 Calls Analysis:** time and location-based patterns of emergency calls.
  2. **Finance Data Analysis:** stock price behaviour, returns, and inter-company correlations.
- Implemented **data ingestion → cleaning → transformation → visualisation** using pandas and numpy for data handling and seaborn/plotly for insight communication.
- Created reusable analysis templates for:
  - Date/time feature engineering (`.dt` accessors, grouping, resampling)
  - String and categorical handling (type conversion, feature splitting)
  - Correlation and pairwise analysis
  - Multi-panel and interactive visualisations for pattern discovery.

## Stack
- **Language:** Python 3  
- **Libraries:** `pandas`, `numpy`, `matplotlib`, `seaborn`, `plotly`, `datetime`  
- **Tools:** Jupyter Notebook, Git/GitHub  
- **Concepts:** EDA, data cleaning, feature extraction, time series analysis, correlation analysis, visualisation design

## Case Studies

### **1. 911 Calls EDA**
**Objective:** Explore temporal and spatial patterns in emergency call data.  
- Parsed timestamps into year, month, day, and hour features for time-based analysis.  
- Mapped call reasons and types to broader categories (e.g., EMS, Fire, Traffic).  
- Visualised daily and monthly call volume, call-type distributions, and temporal trends.  
- Identified operational peaks and seasonal call variation patterns.

**Skills:** datetime manipulation, grouping and aggregation, categorical encoding, visualisation (line, bar, count, heatmap).

---

### **2. Finance Data EDA**
**Objective:** Investigate stock price dynamics and inter-company behaviour.  
- Collected multi-stock price data via Yahoo Finance API.  
- Calculated moving averages, daily returns, and cumulative returns.  
- Conducted pairwise correlation and risk–return analysis across multiple tickers.  
- Visualised price trends and co-movement patterns through heatmaps and scatter matrices.

**Skills:** time-series analysis, rolling windows, correlation matrices, multi-plot visual storytelling.

---

## Results
- Demonstrated **consistent EDA methodology** applicable across domains.  
- Built a reproducible framework highlighting how to structure exploratory workflows for both categorical–temporal and continuous–financial data.  
- Strengthened proficiency in **data storytelling and visualisation** using modern Python tools.

## Impact
- Forms the **analytical bridge** between raw data handling and predictive modelling.  
- Provides an adaptable template for future projects involving data cleaning and insight extraction.  
- Complements the “Python OOP Mini-Systems” repository by demonstrating **data-centric rather than logic-centric** Python application.

## Links & Resources
- 💻 **Code repository:** [GitHub – Python EDA Projects](https://github.com/AlejandroFuentePinero/python-eda-mini-projects)

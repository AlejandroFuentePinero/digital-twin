# Data Science Skill Labs

Short, targeted builds designed to cement specific skills through implementation.

---

## MLB Analytics with SQL
**GitHub:** https://github.com/AlejandroFuentePinero/MLB_Analytics_Project

End-to-end SQL analytics project using the Lahman Baseball Database (150 years, 1871–2024). Designed a complete relational workflow with schema creation, reusable views, advanced CTEs, window functions, and business-focused analyses.

**Four analytical pillars:**
1. Talent Pipelines — which colleges produce the most MLB players, and how has that shifted by decade?
2. Salary & Payroll Dynamics — team spending patterns, cumulative milestones, decade-level comparisons
3. Player Career Analysis — career length, debut/retirement windows, age distributions, team loyalty
4. Player Profiles — height/weight trends, cross-era comparisons, physical attributes of standout players

**Key findings:** low-payroll teams consistently outperforming expectations; decade-level shifts in college talent pipelines; physical attribute differences between Hall of Fame and non-HOF career trajectories.

**SQL highlights:** window functions (RANK, NTILE, cumulative SUM), multi-step CTE pipelines, statistical SQL (COVAR_POP, VAR_POP for trend estimation), date manipulation, NULL-aware profiling, reusable view architecture.

**Stack:** PostgreSQL · Python · pandas · matplotlib · seaborn

---

## Python ML Projects
**GitHub:** https://github.com/AlejandroFuentePinero/python-ML-projects

Core ML algorithms implemented and applied through end-to-end workflows: data prep → model training → evaluation → visualisation.

**Coverage:** Linear/Polynomial Regression, Logistic Regression, KNN, Decision Trees, Random Forests, SVM, Gradient Boosting/XGBoost, K-Means, Hierarchical Clustering, PCA, NLP (Naive Bayes, TF-IDF), Deep Learning (TensorFlow/Keras), Recommender Systems, Cross-validation, intro PySpark.

**Stack:** Python · scikit-learn · pandas · NumPy · matplotlib · seaborn · XGBoost · TensorFlow · Keras

---

## Python OOP Mini Systems
**GitHub:** https://github.com/AlejandroFuentePinero/python-oop-mini-systems

Suite of applied Python mini-systems demonstrating progression from procedural to object-oriented design.

**Examples:** Tic-Tac-Toe (procedural decomposition), Blackjack (class composition: Card/Deck/Hand/Chips), Credit Card Validator (Luhn algorithm), Bank Account Manager (inheritance/polymorphism), Product Inventory (CRUD), Library Lending System (Item subclasses, Member, Loan tracking).

**Stack:** Python 3 · OOP (composition, inheritance, polymorphism) · datetime · re

---

## Python EDA Mini Projects
**GitHub:** https://github.com/AlejandroFuentePinero/python-eda-mini-projects

Applied EDA on two real-world datasets demonstrating data wrangling, feature extraction, and visual storytelling.

**Case studies:**
1. **911 Calls EDA:** temporal and spatial patterns in emergency call data — timestamp parsing, call-type distributions, seasonal variation, operational peaks.
2. **Finance Data EDA:** stock price dynamics — moving averages, daily returns, pairwise correlations, risk-return analysis across tickers.

**Stack:** Python · pandas · NumPy · matplotlib · seaborn · plotly

---

## MTG Mana Calculator
**GitHub:** https://github.com/AlejandroFuentePinero/mtg-mana-calculator

A browser tool for Magic: The Gathering players to calculate optimal land counts and colour sources using Frank Karsten's heuristics. Because even card games deserve a rigorous model.

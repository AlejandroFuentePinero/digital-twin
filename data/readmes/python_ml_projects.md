# Python ML Projects — Core ML Algorithms Lab

**Source:** https://github.com/AlejandroFuentePinero/python-ML-projects

## What it is

A curated collection of **end-to-end machine learning projects** in Python, each demonstrating practical problem-solving across the full workflow: data preparation → model training → evaluation → interpretation. Designed as a learning lab to consolidate ML fundamentals through implementation, with each project documented as a self-contained Jupyter notebook covering problem framing, methods, key decisions, and results.

The deliberate emphasis: not just *how* to build models, but *why* they behave as they do — error analysis, model interpretability, and honest communication of trade-offs.

## Project catalogue (11 projects)

| # | Project | Focus |
|---|---|---|
| 01 | Linear Regression | Predicting a continuous target; feature scaling, trend interpretation, error analysis |
| 02 | Logistic Regression | Binary classification; decision thresholds, precision/recall, ROC–AUC |
| 03 | K-Nearest Neighbors | Distance metrics, bias–variance trade-off |
| 04 | Decision Trees + Random Forest | Non-linear decision boundaries, feature importance, overfitting control |
| 05 | Support Vector Machines | Decision boundaries, kernel tricks, margin interpretation |
| 06 | K-Means Clustering | Choosing k, interpreting cluster structure |
| 07 | Recommender Systems | Item/user similarity, collaborative filtering basics |
| 08 | NLP (Naive Bayes) | Text classification; tokenisation, vectorisation, baseline NLP workflows |
| 09 | NN Keras (regression) | Feedforward neural net for regression; architecture design, regularisation |
| 10 | NN Keras (classification) | Neural network classifier; class imbalance handling |
| 11 | NN LendingClub (credit risk) | Risk-perspective evaluation; threshold tuning for cost-asymmetric outcomes |

## Architecture (per-project structure)

Each project folder contains:

- A **Jupyter notebook** documenting the problem, methods, key decisions, and results
- All **datasets** used for training and testing
- Clear explanations of limitations, assumptions, and takeaways

## Algorithms and techniques covered

| Category | Algorithms / Methods | Skills Demonstrated |
|---|---|---|
| **Regression** | Linear, Polynomial Regression | Error analysis, regularisation, metric interpretation |
| **Classification** | Logistic Regression, KNN, Decision Trees, Random Forests, SVM | Metric trade-offs, confusion matrix analysis, probability thresholds |
| **Clustering** | K-Means | Choosing `k`, interpreting clusters, unsupervised insights |
| **Dimensionality Reduction** | PCA | Feature compression, explained variance, visualisation |
| **NLP** | Naive Bayes | Text preprocessing, tokenisation, vectorisation |
| **Deep Learning** | Feedforward Neural Networks (TensorFlow/Keras) | Architecture design, optimisation, evaluation |
| **Recommender Systems** | Similarity-based and collaborative filtering | Neighbourhood methods, ranking, user–item matrices |

## Key engineering decisions

- **Each project is end-to-end, not a code-snippet collection.** Data prep → modelling → evaluation → interpretation in one notebook per project. This is the realistic shape of an applied ML workflow; demonstrating it across 11 algorithms gives a portfolio-grade survey.
- **Learning focus on *why* models behave as they do**, not just how to call `.fit()`. The notebooks emphasise error analysis, bias–variance reasoning, threshold interpretation — the conceptual machinery that separates "ran the algorithm" from "understands when it'll fail."
- **Honest evaluation including limitations and assumptions.** Each notebook documents what wasn't tested, what assumptions were made, and where the model would break in production. Standard practice in research; rarer in tutorials.
- **Cross-validation, hyperparameter optimisation, and metric selection treated as first-class topics**, not afterthoughts. The notebooks demonstrate the discipline of choosing the right metric for the problem (precision vs recall vs F1 vs AUC) rather than reporting whichever number happens to look best.

## Stack

Python · NumPy · pandas · matplotlib · seaborn · scikit-learn · TensorFlow / Keras · XGBoost · Jupyter

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

---

## MTG Deck Optimisation Engine
**GitHub:** https://github.com/AlejandroFuentePinero/deck-optimisation-engine

A personal research tool built in August 2026 for his own Magic: The Gathering tournament preparation. It mines published MTGO decklists for a single Modern archetype and answers a fixed set of questions about what that archetype's sub-groups (its "camps") are registering: what they play, what they have moved off, which cards are climbing, and where the pilot's own 75 cards deviate from the camp. A sequential scraper caches every published Modern event to disk, a DuckDB store is rebuilt from that cache on each run, and output is a CLI plus one self-contained HTML report. Open source under the MIT licence, 163 tests over committed payload fixtures. It is a working tool for one player and one deck, explicitly not a product. Frozen in September 2026: its tracking half continued as Archetype Tracking (below), and the play-by-play question it could not answer from decklists is what MTGO Insights (below) was built to answer from game logs.

**The interesting artefact is the postmortem, not the tool.** Alejandro audited the engine against its own database and published a verdict that vindicates the engineering and condemns the premise: published decklists are conditioned on winning (challenges publish only the top 32, leagues only 5-0 runs, losing lists never appear at all), so every performance instrument in the engine runs at 6-9% statistical power against effects an order of magnitude smaller than its own detection floor. The adoption measurements survive that audit; the performance ones were downgraded in place to disconfirmation instruments, able to rule out a large effect but never to confirm a small one. Each reading names the population it was taken over, and the engine refuses to print a share across two populations. Same refusal discipline as 7PH Graph, applied to a tool whose only user was himself, which is the case where nobody would have caught it.

**Stack:** Python 3.12 · DuckDB · uv · pytest

---

## MTGO Insights
**Source:** private repository (see below for why)
**Deployed:** protected Hugging Face Space, reachable only with a contributor login

Built in August 2026 for his Modern testing team's preparation for the Brisbane tournament (28 to 30 August 2026). Where the Deck Optimisation Engine could only read what winners registered, this reads what both seats of a match actually did: MTGO game logs that teammates send in, parsed into matches, games, casts and stated interactions, and served as a Gradio dashboard. Home is the tracked field played against itself as a matchup matrix. Behind it, one tab per tracked archetype (the fifteen with the most matches, recomputed on every build) shows the deck's match and game record, its matchups split on the play / on the draw and preboard / postboard, and a card table. Within weeks the corpus passed 2,000 matches and 5,000 games. Used through the team's testing season; it changed some of his own deck decisions.

**What the engineering is:**
- **Explicit-only, event-grained extraction.** The parser records only what the log states (a cast, a target, a counter, an attack), never an inferred outcome, and drops the blocks MTGO restates after a reconnect, which would otherwise invent games and inflate card counts. The SQLite artifact is rebuilt whole from the committed logs on every build.
- **Deck identity is inferred, and the inference is audited.** Archetypes are assigned by hand-curated Signature Rules (one high-precision card, or a required co-occurrence), ordered by specificity. A Review Queue lists every match that landed unassigned and every verdict a rival rule came within one card of, so hand Overrides are decided from evidence and are the seed of the next rule. Overrides live in a file beside the inferred verdict, never over it, so they survive the rebuild and the disagreement stays visible. About 95% of classification runs unattended; his input is new rules as the metagame shifts.
- **Only the figures the logs can support.** Cast-Conditional Winrate is the one card winrate available, because a card never drawn is indistinguishable from a card never in the deck. It is read against a Deck Baseline recomputed over exactly the same games, per board, never against a flat 50%, and the app refuses cross-card comparisons. Every rate prints its sample size; a cell is coloured only when its interval clears the neutral band; cards under a cast threshold are not shown at all. Every figure is bounded to the current Format Era, because a rate carrying games from a format that no longer exists is a wrong answer rather than a longer-run one.
- **Privacy decided the deployment.** The database joins real MTGO usernames to inferred decklists and records, which is unremarkable on a laptop and different once published, so the source is private and the Space is protected: the running app answers only to per-contributor logins minted from a roster, the artifact is read-only and prebuilt, and the Space carries no ingestion code, no write path and no credentials. Deck reports are computed at boot, and the two indexes that made that cheap were chosen by measurement (fifteen reports in about 1.3 s) rather than by reasoning.
- **Documented like a production system.** A glossary-first `CONTEXT.md` with explicit "avoid" lines for near-synonyms, 23 architecture decision records, and 325 tests over committed log fixtures.

**Stack:** Python 3.13 · SQLite · Gradio · PyYAML · pytest · uv · Hugging Face Spaces (protected, Gradio auth)

---

## Arena Insights
**Source:** private repository, same reason as its sister

Started in September 2026 as the sister of MTGO Insights for the same team's Standard best-of-three testing on MTG Arena. It is a deliberate copy that diverges rather than a shared package (ADR-0003): the query builder, rate helpers and deploy flow are thin next to the parser, schema, classifier rules and card table that had to change, and a shared package would have meant speculative extension points in an app that already worked. Ports between the two are recorded, so a fix that never crosses is a chosen divergence rather than a silent one.

**What is new rather than ported:**
- **A different kind of log.** MTGO logs are sentences; Arena logs are Unity console text with the Game Rules Engine's JSON state embedded in it, roughly a hundred times larger per match. Extraction is state-diff grained: casts, attacks and deaths are derived by diffing zones and reading annotations, and cards are keyed by title id against a snapshot of Arena's card database, which rotates under a new hash on every client update. Before any code existed he measured what the logs actually state, and verified the visibility model on every match in the starting corpus: the log owner's own hand carries card identities from the opening hand on, the opponent's hidden information never does.
- **The log owner's private seat.** Opening hands, mulligans, draws and per-game sideboard lists exist only for the pilot's own seat, and they are the reason the project exists. They are read with 17lands' vocabulary (Games Played, Opening Hand, Games Drawn, Games in Hand, Games Not Seen, In-Hand Winrate with its lift over the never-seen games), so a player already fluent in those figures reads them without a legend. Public figures pool both seats as the sister does; private figures read the pilot seat only; one card row carries both populations and shows both counts rather than hiding the difference (ADR-0002).
- **A store of record that survives the client.** Arena purges its own log archive without warning, so session logs are trimmed to the engine messages and deck submissions (a filter, never a transformation, so a build from the trimmed form equals a build from the raw one) and the trimmed archive is committed as the store of record.

7 architecture decision records and 368 tests, most of them inherited from the sister and re-pointed at Arena fixtures.

**Stack:** Python · SQLite · Gradio · pytest · uv · Hugging Face Spaces

---

## Archetype Tracking
**GitHub:** https://github.com/AlejandroFuentePinero/archetype-tracking (public, MIT)

The tracking half of the Deck Optimisation Engine, split out in September 2026 into a tool of its own and pointed at the team meeting rather than at one player's 75. It reads published Magic: The Gathering decklists (every MTGO event, plus configured paper events fetched from Melee) and reports named Modern archetypes fortnightly: how much of the field an archetype holds, whether that presence converts into finishes, whether it is still being built or merely copied, and which slots of its build moved. The readings render as a weekly HTML report with inline SVG figures and a hand-written summary at the top.

**What carried over from the postmortem, and what the split added:**
- **Adoption, never performance.** The engine keeps the audit's verdict as a design rule: published lists are conditioned on winning, so it measures what pilots registered and how that moved from one fortnight to the next, and where a figure looks like performance it is printed as a share of a cut over a share of a field, with both counts.
- **Frozen rows.** Everything the report has ever said is committed and append-only, because the report's own history cannot be rebuilt from a cache: a past week genuinely moves when a late league dump fills in, and the frozen row is what was reported at the time.
- **Populations never share an axis.** Paper events publish every finisher where an MTGO challenge publishes a cut, so paper lists never enter the MTGO store and are read as storyline entries beside it rather than pooled into it.
- **Polite data collection.** A sequential scraper with no parallelism, retrying a page with lengthening backoff because the source intermittently serves a 200 whose content is missing, and a stub taken at face value silently drops published lists. A played-out paper event is fetched once and never again.

DuckDB store rebuilt from the disk cache on every run; a glossary-first `CONTEXT.md`; ADR 0001 records what four days of backfill established about the MTGO stream; 78 tests over committed payload fixtures.

**Stack:** Python 3.12 · DuckDB · matplotlib · uv · pytest

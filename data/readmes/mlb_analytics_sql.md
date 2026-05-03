# MLB Analytics — Lahman Database (1871–2024)

**Source:** https://github.com/AlejandroFuentePinero/MLB_Analytics_Project

## What it is

End-to-end SQL analytics project using the **Lahman Baseball Database** (150 years of MLB history, 1871–2024). Designed as a portfolio-grade demonstration of professional relational modelling, advanced query design, analytical view architecture, and performance optimisation — paired with a substantive exploration of MLB's evolution across talent pipelines, salaries, careers, and physical traits.

The dual purpose is intentional: a **SQL-skills demo** that doubles as a real piece of analysis, rather than a contrived "find the duplicates" toy.

## Architecture

Layered analytical stack:

### Schema layer

- Manual relational schema creation from raw CSVs (`sql/schema.sql`).
- Optional analytical schema (`mlb_analytics`) for clean separation between source tables and derived views.

### Analytical views

- Reusable views (`sql/views.sql`) define commonly-used joins, filters, and aggregations.
- Downstream queries consume views rather than re-deriving the same logic — DRY at the SQL layer.

### Query layer

Three tiers of queries:

- **`analysis_queries.sql`** — core business questions answered against the views.
- **`advanced_queries.sql`** — extended portfolio analysis with multi-step CTE pipelines.
- **`optimised_queries.sql`** — view-based refined versions demonstrating performance tuning.

### Visualisation layer

- Jupyter notebook (`notebooks/mlb_visual_analysis.ipynb`) integrates pandas with SQL for chart-driven exploration.

## Four analytical pillars

Each pillar is a substantive subprojects, not a token query exercise:

### Part I — Schools and MLB talent pipelines

- ~28% of MLB players have a documented college affiliation, spread across 1,100+ schools — large, decentralised talent system.
- School representation increases sharply post-1950, driven by collegiate baseball growth and improved scouting.
- Geographic shift: early talent from Northeast/Midwest, modern pipelines favour South/West.
- Schools with established baseball programs produce more players and longer careers.

### Part II — Salary, payroll evolution, competitive dynamics

- Salary dataset (1985–2016) captures the modern era of escalating budgets.
- Yankees lead cumulative payroll spending by a clear margin; Red Sox / Dodgers / Mets are heavy spenders without matching multi-decade consistency.
- Median payroll ~2/3 of top-tier — structural financial inequality.
- Postseason success closely associated with higher payrolls.

### Part III — Career trajectories, longevity, team loyalty

- Most MLB careers are short; only a minority sustain decade-long tenures.
- Hall of Fame players debut younger, play longer, accumulate more games than non-inductees.
- Team mobility is common; relatively few players are one-franchise lifers.

### Part IV — Player comparison and physical profiles

- Height/weight data >90% complete.
- Average debut height: ~5 ft 8 in (early era) → >6 ft 1 in (modern). Weight increased even more.
- Pitchers debut slightly taller and heavier than non-pitchers.
- AL and NL show nearly identical physical profiles per era.

## Key engineering decisions

- **Manual schema creation rather than ORM autogeneration.** The CSVs come without explicit constraints; manual schema design lets the project demonstrate primary keys, foreign keys, and indexing decisions appropriate to the data shape. Required for the SQL-skills aspect of the portfolio.
- **Reusable analytical views rather than ad-hoc joins.** Common joins (player-team-season, player-batting-fielding) live as views consumed by all downstream queries. Avoids divergence between business questions; keeps the SQL DRY.
- **CTE pipelines over nested subqueries.** Multi-step CTEs (`WITH x AS (...), y AS (...)`) make complex analyses readable, testable in isolation, and easier to debug. Demonstrates window functions (`RANK`, `NTILE`, `LAG/LEAD`, cumulative `SUM`), statistical SQL (`COVAR_POP`, `VAR_POP`), and date manipulation idioms.
- **Three query tiers (analysis / advanced / optimised) as pedagogical scaffolding.** The same business question can be answered with naive joins or with view-based optimised queries; both are kept and labelled so the portfolio shows both correctness and performance awareness.
- **Integrated Python/SQL workflow in the notebook.** Pandas reads SQL directly, demonstrating the realistic analyst workflow rather than treating SQL and Python as separate worlds.

## Stack

PostgreSQL · Python · pandas · matplotlib · seaborn · Jupyter

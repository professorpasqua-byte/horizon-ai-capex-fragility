# Horizon: do stretched teams break systems?

A made-up tech company, a year of deliberately ugly data, and a project that grades its own answers.



![tests](https://github.com/professorpasqua-byte/horizon-ai-capex-fragility/actions/workflows/tests.yml/badge.svg)



[Live dashboard](https://horizon-ai-capex-fragility-3zizerbeayebfpyetyswac.streamlit.app/)

**Project site:** https://professorpasqua-byte.github.io/horizon-ai-capex-fragility/
**Companion projects:** [Vanguard](https://github.com/professorpasqua-byte/vanguard-tech-ghost-badging) and [Aegis](https://github.com/professorpasqua-byte/aegis-systems-survival-analysis)

---

## The short version

Cloud providers had a rough 2026. Analysts had warned it would happen, and the reason they gave was money: AI was pulling budget away from older infrastructure and into GPU data centers. When the outages came, the reported causes were things you can point at, like a cooling failure, a power fault, a fiber job that went wrong.

What nobody outside those companies can see is whether the people running the systems were stretched too thin. Staffing levels, overtime and ticket backlogs are not published anywhere.

I am an industrial psychologist, so that is the part I wanted to test. There is no real data to test it on, so I built a company. Horizon is fictional, but I control everything about it, including the answer. I buried a set of rules in a year of simulated data, made the data as messy as a real company's, built a pipeline to clean and join it, and then asked three models to find what I buried. At the end the project marks its own work, including the parts it got wrong.

| | |
|---|---|
| Hourly infrastructure records | 245,280 (28 clusters x 8,760 hours) |
| Source systems | 6, each arriving at its own speed and broken in its own way |
| Architecture | Bronze, silver and gold layers (medallion), plus a DuckDB layer with SQL checks |
| Join logic | Strict as-of joins on delivery date, so no row knows anything from its own future |
| Tests | 95, warnings treated as errors, run on every push |
| Models | 3, all graded against a hidden answer key |
| Result | 11 of 13 checks hit, 2 honest misses |

**What it found, in plain English**
- Outages follow strain by about **6 weeks**. The model found 6, the number I buried.
- Teams that feel unsafe stay quiet. Low-safety teams filed a ticket for **67%** of real outages. High-safety teams filed **93%**. I planted 65% and 95%.
- Every stressed team was flagged before its outages truly started to climb, about 3.5 weeks before the buried tipping point.
- The protected control region never raised a false alarm.
- The tipping point itself came out at **0.81** against the **0.72** I buried. That is a miss, and the dashboard says so.

---

## The real-world problem

### What was predicted
In its Predictions 2026 research, Forrester said to expect at least two major, multiday outages at the big cloud providers in 2026. The reason it gave was where the money was going: spending shifting from older infrastructure toward GPU data centers built for AI.

### What happened
Dates and durations below come from outage trackers and trade press. The providers' own post-incident reports are the primary record.

- **October 2025.** AWS US-EAST-1 suffered a DNS fault around DynamoDB with knock-on trouble for most of a day. Azure Front Door failed for about 8 hours later that month.
- **February 2026.** Azure had a regional problem in West US that ran past 20 hours.
- **7 to 8 May 2026.** AWS lost cooling in one US-EAST-1 data hall. Depending on whose clock you use, full recovery took between 19 and 28 hours.
- **15 July 2026.** A utility power fault took out cooling at a Google Cloud site in the Netherlands. Roughly 12 to 15 hours.
- **20 August 2026.** Google Cloud us-west1 lost 33 services for 2 hours 22 minutes after planned fiber maintenance went wrong and automatic rerouting failed.

Whether that adds up to Forrester's "multiday" is a fair argument. The pattern I care about is the cause.

### The gap
Every cause on that list is physical or procedural: cooling, power, cables, maintenance. Nobody published how many engineers were on shift, how much overtime they were working, or whether the ticket backlog was growing. That data is private, so the question "do stretched teams make failures more likely?" cannot be answered from outside.

I am **not** claiming people caused any of these outages. The reported causes were physical. I am asking a narrower question: if a company wanted to see this risk building inside its own teams, what would the data look like, and could it be seen early enough to matter?

My two earlier projects looked at the people side of tech restructuring. Aegis asked whether low attrition after AI-linked layoffs means a healthy team or just people with nowhere to go. Vanguard asked whether a model can find a hidden tipping point and grade itself. Horizon joins them.

---

## The psychology behind it

The human side rests on established theory from my own field. Each framework became a specific mechanism in the simulation, and the analysis then asks whether the data can pick that mechanism up.

| Framework | The idea | What it became in Horizon |
|---|---|---|
| **Job Demands-Resources model** (Demerouti, Bakker, Nachreiner and Schaufeli, 2001; Bakker and Demerouti, 2007) | Strain builds when job demands rise and the resources to meet them shrink | Demands are the AI-driven workload. Resources are funded headcount. The ratio between them is the capacity-to-load ratio. Overtime is the strain signal |
| **Conservation of Resources theory** (Hobfoll, 1989) | People work to protect resources, losses hurt more than gains help, and losses feed on themselves | Strain raises the chance that people leave, and every departure makes the remaining team's load heavier. That loop is built into the staffing simulation |
| **Psychological safety** (Edmondson, 1999) | Whether people feel safe admitting problems and mistakes | Every team has a hidden safety level. Low-safety teams skip the ticket for 35% of real incidents, against 5% elsewhere. A monthly pulse survey measures it, with noise |
| **Layoff survivor research** (Brockner and colleagues, 1980s) | The people who stay after cuts carry extra load, uncertainty and worry | A hiring freeze and reductions start the moment a region begins moving budget into AI, so the team that remains is smaller while demand grows |

Two more things from this literature shaped the design. Strain does not hit all at once, it wears people down, so outages respond **weeks later** and not instantly. And resource loss tends to matter most once it passes a critical point, so I used a **threshold** with a ramp instead of a straight line.

One honest note. The theory says strain accumulates and that thresholds exist. It does not hand me the numbers. The 0.72 threshold and the 6-week delay are my assumptions, chosen to be plausible. This is a demonstration of how to look for such effects, not evidence about any real company.

---

## The fictional company

**Horizon Infrastructure Group** runs 28 clusters across 4 regions, looked after by 8 site reliability teams, over one simulated year (1 October 2025 to 30 September 2026).

Budget moves into AI one region at a time:

| Region | Starts moving budget into AI | Role |
|---|---|---|
| na-east | October to December 2025 | First to be squeezed |
| eu-west | January to March 2026 | Second |
| apac-south | April to June 2026 | Third |
| latam-central | Never | Protected control region |

After a region starts, 5 percentage points more of its total budget moves to AI each quarter, capped at 20. Core maintenance starts at 60% of the budget, so funded headcount shrinks as that share does. Demand grows 8% over the year, plus more load for every point of budget moved to AI. Backfilling a leaver is slow during a hiring freeze (8% of the gap filled per week, against 30% normally). Strain pushes up overtime and the chance of people leaving.

### What I buried
| Rule | Value |
|---|---|
| Strain threshold | Outage risk stays flat until a team's capacity-to-load ratio falls below **0.72**, then climbs over the next 0.10 |
| Delay | Risk responds to the ratio from **6 weeks earlier**, not today's |
| Competing cause | Deferred maintenance from budget cuts also raises outages, so people are not the only explanation |
| Under-reporting | Teams with low psychological safety skip the ticket for **35%** of real incidents, against **5%** for the rest |
| Under strain | Outages last longer, are more severe, and are more often caused by process errors than by hardware |

Hardware behaves like hardware. Latency follows a queueing curve, so it creeps along and then shoots up. Temperature rises with load and with deferred maintenance, throttling starts above 75 degrees C, and packet drops climb once utilization passes 70%.

---

## The data is messy on purpose

Real companies do not hand you clean tables. Each of the 6 sources arrives at its own pace with its own flaws, and a ledger records exactly what I broke so the cleaning can be graded.

| Source | Pace | What I broke |
|---|---|---|
| Telemetry (245,089 rows) | Near real time | 723 exact duplicates, 494 restated readings, 1,198 missing, 472 sensor glitches (-999), 4,974 arriving hours late, and 60,999 rows from apac-south logged in local time as if it were UTC |
| Monitoring itself | During outages | 210 hours lost during severe outages, because monitors go quiet exactly when you need them |
| Staffing | Weekly, days late | Team names spelled three ways, 13 missing weeks, restated rows, -1 for missing overtime |
| Budget | Quarterly | Money stored as text (like $12.50M), some quarters restated 45 days later |
| Tickets (6,872 rows) | Daily batch | latam-central stamped with a -03:00 offset, 68 duplicates, 190 blank severities |
| Post-mortems | Days after | Root cause typed as free text |
| Pulse survey | Monthly | Scores hidden for teams with fewer than 5 responses |

---

## How it is built

    simulate -> landing (messy) -> bronze -> silver -> gold -> SQL + models -> grading -> dashboard
                                    as-is    cleaned   joined    DuckDB       vs the hidden
                                                       as-of     3 models     answer key

- **The simulator is seeded.** The same seed always gives the same world, and a test enforces it. The hidden truth is written to its own folder.
- **Bronze** takes every source exactly as delivered, adds load metadata, and refuses any answer-key table outright.
- **Silver** cleans it. The timezone problem is found from the data itself: it compares each cluster's reported time with when the reading actually arrived, and it picks out exactly the 7 apac-south clusters at +8 hours without being told. It also removes duplicates (latest delivery wins), nulls the sentinels, turns three spellings of a team name into one, parses the money text and the ticket timestamps with their offsets, and keeps every delivered version of the slow sources.
- **Gold** builds a complete grid of 245,280 cluster-hours, plus a team-week table of 416 rows. Gaps stay visible as gaps. Nothing is quietly dropped.
- **Strict as-of joins.** Staffing, budget and survey data are joined using the date each record was *delivered*, not the date it describes. A row for a given hour only knows what the company knew at that moment. When two versions of a week exist, the newest week wins. This is what stops future data leaking backward into the analysis, and it fixes a limit I flagged in my Aegis project. A test checks 150 random points against a brute-force lookup.
- **A DuckDB layer** holds the gold tables. Three SQL files compute the capacity index with window functions, summarize regions by quarter, and run 10 data-quality checks. A test confirms the SQL and the Python give the same capacity index to within one billionth.
- **Guard rails.** Tests fail if the pipeline or the models import the simulator or read the truth folder. The pipeline also runs 17 of its own quality checks every time.
- **Speed.** Everything is vectorized, with no row-by-row loops. The in-memory bronze to gold run over 245,280 rows takes about a third of a second.

### The three models
1. **Tipping point and delay.** A Poisson regression of detected outages on a ramp of the lagged capacity index, controlling for maintenance wear. It searches a grid for the threshold, the ramp width and the delay. The intervals come from the profile likelihood, widened for overdispersion.
2. **Early warning.** A team is flagged when its capacity index sits below the tipping point for two weeks in a row.
3. **Reporting gap.** Outages are detected from telemetry (failed health checks), which does not depend on anyone filing anything. Each is matched to a ticket on the same cluster. The filing rate is then compared with the team's survey score.

The capacity index is staffing relative to demand, where 1.0 is where each team started. The analysis cannot see true workload, so CPU use stands in for it. That stand-in is the reason for the miss below.

---

## Results, graded against the answer key

On the standard run, 11 of 13 checks hit.

| Check | Found | Truth | |
|---|---|---|---|
| Tipping point (ratio) | 0.81 | 0.72 | Miss |
| Tipping point interval covers the truth | 0.73 to 0.84 | 0.72 | Miss |
| Delay between strain and outages | 6 weeks | 6 | Hit |
| Delay interval covers the truth | 6 to 6 | 6 | Hit |
| Outage rate multiplier at full strain | 8.1x | 6x | Hit |
| Filing rate, low-safety teams | 67% | 65% | Hit |
| Filing rate, high-safety teams | 93% | 95% | Hit |
| Low-safety teams identified from the survey | 8 of 8 | 8 of 8 | Hit |
| Control teams falsely flagged | 0 | 0 | Hit |
| Teams flagged before the true risk rose | 100% | 100% | Hit |
| Warning week against true crossing week | 3.5 weeks early | 0 | Hit |
| Timezone-shifted clusters found | 7 | 7 | Hit |
| Telemetry duplicates removed | 1,217 | 1,217 | Hit |

One lucky run proves nothing, so I ran all of it across 8 different simulated worlds. The average was **11.0 of 13**.

| Check | Worlds hit (of 8) |
|---|---|
| Filing rates, survey identification, timezone fix, duplicates | 8 |
| Delay interval covers the truth | 8 |
| Delay within a week of the truth | 7 |
| No false alarm on the control region | 7 |
| Teams flagged before the true risk rose | 6 |
| Warning week close to the true crossing | 6 |
| Tipping point within 0.05 of the truth | 5 |
| Outage rate multiplier | 5 |
| Tipping point interval covers the truth | 4 |

I would rather show you where my method misses than hide it. The tipping point is the weak spot. It is estimated from CPU use standing in for real workload, so it can drift, and its interval was too narrow in half the worlds. Early warning also uses a threshold estimated from the whole year, which makes the backtest more generous than a live system would be.

---

## What this means, and what to do about it

**What is going on.** When a region moves budget into AI, two things happen together: the funded team gets smaller and the workload gets bigger. Staffing relative to demand falls. The first signs are the visible ones, overtime and a growing ticket backlog. This is the Job Demands-Resources pattern: demands up, resources down. Then people leave, and each departure makes the load heavier for those who stay, which is the loss spiral from Conservation of Resources theory. About six weeks after a team crosses the line, real outages start to climb. And the teams under the most strain, if they also feel unsafe, report less. Their ticket queue looks calmer than the truth.

| What Horizon found | Why it happens | What the theory points to |
|---|---|---|
| Outages follow strain by about 6 weeks | Strain wears performance down gradually, it does not break it at once | Watch the leading signals (capacity against demand, overtime, backlog), not outage counts. There are weeks to act, not hours |
| Overtime and backlog rise before outages | Resources run down, and effort is the first thing spent | Treat sustained overtime above a team's normal as a trigger to act, not as proof of commitment |
| Losing people makes it worse | The loss spiral: fewer people, heavier load, more leavers | Backfill quickly in the teams that are stretched. A hiring freeze does the most damage where load is rising fastest |
| Teams that feel unsafe stay quiet | Psychological safety decides whether problems get reported | Detect outages from system data, not from tickets. Make reporting low-risk with blameless post-mortems. Do not judge a team by its ticket count, because fewer tickets can mean less safety |
| Budget moved in stages | A threshold effect: little changes, then a lot | Move budget in steps and re-measure capacity before the next step. Keep a protected comparison group of teams or regions |

At the job level, the Job Demands-Resources model gives two levers. Lower the demands (narrower scope, lighter on-call load, fewer simultaneous projects) or add resources (more people, better tooling, more autonomy, real support). Doing neither while cutting the maintenance budget is the one option the model says will fail.

The Budget view in the dashboard lets you see this directly: pick how much budget has moved into AI and see how teams looked at that level.

**What I am not claiming.** These are the actions the theories point to, and Horizon shows the warning signals are detectable weeks ahead. It does not prove that acting on them would prevent a real outage. That would take real data and a proper intervention study.

---

## Limits
- Everything here is synthetic. It says nothing about any real company, and nothing about what caused any real outage.
- The strain mechanism is a hypothesis built from job-demands theory. The threshold and the delay are my assumptions.
- The tipping point is the least reliable result, for the reason above.
- With about 130 detected outages per run, some estimates are noisy. That is why the project reports intervals and a multi-world sweep and not one headline number.

---

## What every file and folder is

    horizon-ai-capex-fragility/
    |-- README.md            this file
    |-- app.py               dashboard home page
    |-- pages/               the other four dashboard pages
    |-- dashboard/           small helpers the pages use
    |-- src/horizon/         all the project code
    |-- sql/                 the SQL layer
    |-- tests/               95 tests
    |-- docs/                data dictionary and method notes
    |-- results/             small result files the dashboard reads
    |-- .github/workflows/   automatic test run
    |-- .streamlit/          dashboard theme
    |-- .devcontainer/       Codespaces setup
    `-- data/                generated locally, not committed

### Top level
- `app.py`: the dashboard home page, with the headline numbers and the chart of capacity by region.
- `pyproject.toml`: packaging, dependencies and test settings (warnings count as errors).
- `requirements.txt`: what Streamlit Cloud installs to run the dashboard.

### `src/horizon/` (the project)
- `config.py`: the one place that defines regions, scale, the simulated window and the buried rules.
- `pipeline.py`: runs bronze, silver and gold, then 17 quality checks, and reads and writes the files.
- `analysis.py`: runs the three models, grades them, and writes the result files.
- `warehouse.py`: loads gold into DuckDB and runs the SQL.

**`simulate/` builds the fictional company**
- `world.py`: regions, teams, clusters, and each team's hidden safety level.
- `budget_staffing.py`: quarterly budgets, the staggered AI diversion, and weekly team staffing with the loss spiral.
- `telemetry.py`: hourly cluster behavior, including the queueing curve, maintenance wear and throttling.
- `incidents.py`: outages, tickets and post-mortems, with the buried threshold, delay and under-reporting.
- `mess.py`: turns the clean world into the messy files each source system would hand over, and records what it broke.

**The pipeline**
- `bronze/ingest.py`: lands every source as delivered and refuses answer-key tables.
- `silver/clean.py`: fixes timezones, duplicates, sentinels, labels, text money and timestamps.
- `gold/build.py`: the cluster-hour and team-week tables, and the as-of join.

**The analysis**
- `models/features.py`: the capacity index and the maintenance wear stand-in.
- `models/hinge.py`: the tipping point and delay model.
- `models/early_warning.py`: flags a team when it sits below the tipping point.
- `models/reporting_gap.py`: finds outages with no ticket and who skips them.
- `grading/grade.py`: compares every finding with the buried answer. It is one of only two places allowed to read the truth.

### `dashboard/` and `pages/`
- `data.py`: reads the result files and prepares what each page shows.
- `style.py`: the indigo header band and chart colors.
- `1_Tipping_point.py`: where outages start to climb and how long after the strain.
- `2_Budget_view.py`: a slider for how much budget moves into AI and what the teams looked like at that level.
- `3_Ticket_gap.py`: real outages that never became a ticket, by team.
- `4_Grading_and_limits.py`: the full scorecard, the misses, and the data-quality checks.

### `sql/`
- `01_views.sql`: the capacity index computed with window functions.
- `02_region_quarter.sql`: capacity, outages, tickets and overtime per region per quarter.
- `03_quality_checks.sql`: 10 data-quality checks on the gold layer.

### `docs/`
- `DATA_DICTIONARY.md`: every table and column. A test fails if one is missing.
- `METHODS.md`: the method notes in short form.

### `results/`
Small files safe to publish: `findings.json`, `grading.csv`, `tipping_profile.csv`, `lead_time_profile.csv`, `early_warning.csv`, `reporting_gap.csv`, `team_signals.csv`, `dq_report.csv`, `cleaning_report.csv`, `sql_checks.csv` and `region_quarter.csv`.

### `tests/`
- `test_world.py`: the company builds the same way every time, and the hidden truth never leaks into a table.
- `test_budget_staffing.py`: the staggered rollout, the control region staying safe, and headcount adding up.
- `test_telemetry.py`: row counts, local time of day, the queueing curve and throttling.
- `test_incidents.py`: the threshold, the delay, the under-reporting and the ticket links.
- `test_mess.py`: every flaw really is in the data, and the answer key stays hidden.
- `test_pipeline.py`: cleaning counts match the ledger, times are recovered exactly, and as-of joins never look ahead.
- `test_models.py`: the models recover the delay and the filing gap, and cannot touch the truth folder.
- `test_dashboard.py`: the dashboard numbers match the findings, and every page compiles.
- `test_warehouse.py`: SQL and Python agree, and all 10 SQL checks pass.
- `test_docs_and_style.py`: the docs cover every column, and this README explains every file.

---

## Run it yourself

    pip install -e . pytest pandas streamlit
    python -m horizon.simulate.world
    python -m horizon.simulate.budget_staffing
    python -m horizon.simulate.telemetry
    python -m horizon.simulate.incidents
    python -m horizon.simulate.mess
    python -m horizon.pipeline
    python -m horizon.analysis
    python -m horizon.warehouse
    python -m pytest -q
    streamlit run app.py

The test suite takes about 15 seconds. It treats warnings as errors and runs automatically on every push.

---

## Built with
Python, NumPy, Polars, DuckDB, PyArrow, pandas, Streamlit and GitHub Actions. The models use plain NumPy, with no machine-learning libraries.

## Sources

**Real-world context**
- Forrester, Predictions 2026: Cloud Outages, Private AI On Private Clouds, And The Rise Of The Neoclouds: https://www.forrester.com/blogs/predictions-2026-cloud-outages-private-ai-on-private-clouds-and-the-rise-of-the-neoclouds
- AWS US-EAST-1, May 2026: https://tech-insider.org/aws-outage-us-east-1-2026/
- Google Cloud us-west1, August 2026 (with a 2026 comparison of AWS and Azure incidents): https://shattered.io/google-cloud-outage-33-services-2026/
- Google Cloud europe-west4, July 2026: https://baxtel.com/news/power-and-cooling-failure-causes-google-cloud-outage-in-netherlands
- The Register's running outage coverage: https://www.theregister.com/tag/outage

**Psychology**
- Demerouti, E., Bakker, A. B., Nachreiner, F., and Schaufeli, W. B. (2001). The job demands-resources model of burnout. *Journal of Applied Psychology*.
- Bakker, A. B., and Demerouti, E. (2007). The job demands-resources model: state of the art. *Journal of Managerial Psychology*.
- Hobfoll, S. E. (1989). Conservation of resources: a new attempt at conceptualizing stress. *American Psychologist*.
- Edmondson, A. (1999). Psychological safety and learning behavior in work teams. *Administrative Science Quarterly*.
- Brockner, J. and colleagues (1980s). Research on how layoffs affect the employees who remain.

## A note on honesty
Horizon is entirely fictional, and the figures in this project describe a simulation I designed. Outage dates and durations in the real-world section come from secondary sources and may differ from the providers' own reports.

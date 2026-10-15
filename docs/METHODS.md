# Methods

## The question
As budget moves from core maintenance into AI, is there a tipping point where systems and the teams running them start to fail, and can the data find it before the outage does?

## The planted answer
The simulation is built with rules the analysis does not get to see:
- Outage risk is flat until a team's capacity-to-load ratio falls below **0.72**, then ramps up over the next 0.10.
- Risk responds to the ratio from **6 weeks earlier**.
- Deferred maintenance (from budget cuts) also raises outages. It is a real competing cause.
- Teams with low psychological safety skip the ticket for **35%** of real incidents, against **5%** for high-safety teams.
- AI budget moves in region by region (na-east, then eu-west, then apac-south). latam-central never diverts and is the control.

## The mess
Each source arrives at its own pace with its own flaws: duplicates, missing and late readings, one region logging local time as UTC, team names spelled three ways, money stored as text, restated quarters, free-text causes, and monitoring that goes quiet during severe outages. A ledger records what was injected so the cleaning can be graded.

## The pipeline
- **Bronze** takes every source as delivered, with load metadata, and refuses any answer-key table.
- **Silver** detects and fixes the timezone shift from the data itself, removes duplicates, nulls sentinels, parses text, maps labels, and keeps every delivered version of slow sources.
- **Gold** builds a complete cluster-hour grid and a team-week table. Slow sources are joined as of the day they were delivered, so no row contains information from the future.
- **SQL** (DuckDB) recomputes the capacity index and runs 10 quality checks on the gold layer. A test confirms SQL and Python agree to 1e-9.

## The models
1. **Tipping point and lead time.** Poisson regression of detected outage episodes on a ramp of the lagged capacity index, with a control for maintenance wear. The knot, ramp width and lag are found by grid search. Intervals use the profile likelihood, widened for overdispersion.
2. **Early warning.** A team is flagged when its index sits below the tipping point for two weeks.
3. **Reporting gap.** Outages are detected from telemetry, then matched to tickets on the same cluster. The filing rate is compared with each team's survey safety score.

The capacity index is staffing relative to demand, with CPU use standing in for demand. 1.0 is where each team started.

## Grading
Each finding is compared with the planted value. On the standard run 11 of 13 checks hit. Across 8 simulated worlds the average was 11.0 of 13.

## Limits
- The tipping point is the weak spot. It rests on a stand-in for workload, it landed within 0.05 of the truth in 5 of 8 worlds, and its interval was too narrow in half of them.
- Early warning uses a threshold estimated from the whole year, so the backtest is generous.
- Everything is synthetic. The strain mechanism is a hypothesis built from job-demands theory, not a finding about any real company.

## Reproduce
Run these in order:

    python -m horizon.simulate.world
    python -m horizon.simulate.budget_staffing
    python -m horizon.simulate.telemetry
    python -m horizon.simulate.incidents
    python -m horizon.simulate.mess
    python -m horizon.pipeline
    python -m horizon.analysis
    python -m horizon.warehouse
    python -m pytest -q

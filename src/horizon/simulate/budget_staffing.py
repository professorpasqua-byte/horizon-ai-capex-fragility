"""Quarterly budget and weekly team staffing for Horizon.

The causal chain planted here:
  AI diversion share rises (staggered by region)
  -> core maintenance and SRE budget falls
  -> funded headcount falls (hiring freeze, then cuts)
  -> capacity-to-load ratio falls, overtime rises, attrition rises (loss spiral)

Observed tables (what a real company would have) are kept apart from latent
tables (the answer key). The latent file goes to data/truth and the analysis
code must never read it.

All money figures are illustrative assumptions, not real data.
"""

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from horizon.config import REGIONS, SCALES, WINDOW_START, SimConfig
from horizon.simulate.world import build_world

Table = dict[str, list]

# Share of the total infrastructure budget that is core maintenance and SRE
# before any diversion. The rest is growth projects.
BASE_CORE_SHARE = 0.60
# Each quarter after diversion starts, one more step of budget moves to AI.
DIVERSION_STEP = 0.05
DIVERSION_CAP = 0.20
# Illustrative quarterly budget per cluster, in millions (assumption).
BUDGET_MUSD_PER_CLUSTER = 5.0
# At the start each team has about 5 percent more people than its load needs.
START_RATIO = 1.05
# Demand growth over the year, and extra demand per unit of AI diversion.
YEARLY_DEMAND_GROWTH = 0.08
AI_DEMAND_FACTOR = 0.8
MIN_HEADCOUNT = 2
# Share of an open gap filled per week. Diversion brings a hiring freeze.
BACKFILL_RATE = 0.30
FROZEN_BACKFILL_RATE = 0.08


def quarter_index(d: date) -> int:
    """0 for Oct-Dec 2025, 1 for Jan-Mar 2026, and so on."""
    months = (d.year - WINDOW_START.year) * 12 + d.month - WINDOW_START.month
    return months // 3


def quarter_start(q: int) -> date:
    month0 = WINDOW_START.month - 1 + 3 * q
    return date(WINDOW_START.year + month0 // 12, month0 % 12 + 1, 1)


def diversion_share(region_id: int, q: int) -> float:
    """Share of the region's total budget moved to AI in quarter q."""
    start = REGIONS[region_id][2]
    if start is None or q < start:
        return 0.0
    return min(DIVERSION_CAP, DIVERSION_STEP * (q - start + 1))


def n_weeks(cfg: SimConfig) -> int:
    return max(1, cfg.scale.days // 7)


def build_budget(cfg: SimConfig) -> Table:
    """One row per region per quarter."""
    last_day = WINDOW_START.date() + timedelta(days=cfg.scale.days - 1)
    n_quarters = quarter_index(last_day) + 1
    out: Table = {
        "region_id": [],
        "quarter": [],
        "quarter_start": [],
        "total_budget_musd": [],
        "ai_diversion_share": [],
        "ai_budget_musd": [],
        "core_budget_musd": [],
        "core_share_of_total": [],
    }
    for region_id in range(len(REGIONS)):
        total = BUDGET_MUSD_PER_CLUSTER * cfg.scale.clusters_per_region
        for q in range(n_quarters):
            d = diversion_share(region_id, q)
            out["region_id"].append(region_id)
            out["quarter"].append(q)
            out["quarter_start"].append(quarter_start(q))
            out["total_budget_musd"].append(round(total, 2))
            out["ai_diversion_share"].append(round(d, 4))
            out["ai_budget_musd"].append(round(total * d, 2))
            out["core_budget_musd"].append(round(total * (BASE_CORE_SHARE - d), 2))
            out["core_share_of_total"].append(round(BASE_CORE_SHARE - d, 4))
    return out


def build_staffing(cfg: SimConfig, world: dict) -> tuple[Table, Table]:
    """Weekly staffing per team. Returns (observed, latent)."""
    rng = np.random.default_rng(np.random.SeedSequence(cfg.seed).spawn(3)[2])
    teams = world["dim_team"]
    weeks = n_weeks(cfg)

    observed: Table = {
        "team_id": [],
        "region_id": [],
        "week_index": [],
        "week_start": [],
        "funded_headcount": [],
        "headcount": [],
        "hires": [],
        "departures": [],
        "reductions": [],
        "overtime_hours_per_head": [],
    }
    latent: Table = {
        "team_id": [],
        "week_index": [],
        "load_units": [],
        "effective_capacity": [],
        "capacity_load_ratio": [],
    }

    for i, team_id in enumerate(teams["team_id"]):
        region_id = teams["region_id"][i]
        start_hc = teams["starting_headcount"][i]
        load0 = start_hc / START_RATIO
        hc = start_hc

        for w in range(weeks):
            wk_start = WINDOW_START.date() + timedelta(weeks=w)
            d = diversion_share(region_id, quarter_index(wk_start))
            funded = max(
                MIN_HEADCOUNT,
                math.ceil(start_hc * (BASE_CORE_SHARE - d) / BASE_CORE_SHARE),
            )

            growth = 1 + YEARLY_DEMAND_GROWTH * w / 52
            load = load0 * growth * (1 + AI_DEMAND_FACTOR * d) * (1 + rng.normal(0, 0.02))
            ratio = hc / load

            strain = max(0.0, 1.0 - ratio)
            p_leave = min(0.5, 0.002 + 0.02 * strain)
            departures = int(rng.binomial(hc, p_leave))
            departures = min(departures, hc - MIN_HEADCOUNT)
            reductions = 0
            if hc > funded:
                reductions = math.ceil(0.15 * (hc - funded))
                reductions = min(reductions, hc - MIN_HEADCOUNT - departures)
            hires = 0
            if hc < funded:
                rate = FROZEN_BACKFILL_RATE if d > 0 else BACKFILL_RATE
                hires = int(rng.poisson(rate * (funded - hc)))
            overtime = max(0.0, 2.0 + 18.0 * strain + rng.normal(0, 0.8))

            observed["team_id"].append(team_id)
            observed["region_id"].append(region_id)
            observed["week_index"].append(w)
            observed["week_start"].append(wk_start)
            observed["funded_headcount"].append(funded)
            observed["headcount"].append(hc)
            observed["hires"].append(hires)
            observed["departures"].append(departures)
            observed["reductions"].append(reductions)
            observed["overtime_hours_per_head"].append(round(overtime, 2))

            latent["team_id"].append(team_id)
            latent["week_index"].append(w)
            latent["load_units"].append(round(load, 3))
            latent["effective_capacity"].append(float(hc))
            latent["capacity_load_ratio"].append(round(ratio, 4))

            hc = hc - departures - reductions + hires

    return observed, latent


def build_budget_staffing(cfg: SimConfig, world: dict | None = None) -> dict:
    world = world or build_world(cfg)
    observed, latent = build_staffing(cfg, world)
    return {
        "fact_budget_quarterly": build_budget(cfg),
        "fact_team_week": observed,
        "latent_team_week": latent,
    }


def write_budget_staffing(tables: dict, root: Path = Path("data")) -> None:
    import polars as pl

    for name, sub in (
        ("fact_budget_quarterly", "raw/budget"),
        ("fact_team_week", "raw/staffing"),
        ("latent_team_week", "truth"),
    ):
        folder = root / sub
        folder.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(tables[name]).write_parquet(folder / f"{name}.parquet")


def crossing_summary(cfg: SimConfig, tables: dict, world: dict) -> list[str]:
    """Answer key view: when does each region first cross the fracture ratio?"""
    lat = tables["latent_team_week"]
    team_region = dict(zip(world["dim_team"]["team_id"], world["dim_team"]["region_id"]))
    fr = cfg.truth.fracture_ratio
    lines = []
    for region_id, (name, _, _) in enumerate(REGIONS):
        first, low = None, 9.0
        for t, w, r in zip(lat["team_id"], lat["week_index"], lat["capacity_load_ratio"]):
            if team_region[t] != region_id:
                continue
            low = min(low, r)
            if r < fr and (first is None or w < first):
                first = w
        crossed = f"week {first}" if first is not None else "never"
        lines.append(f"{name:14s} lowest ratio {low:.2f}  first below {fr}: {crossed}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Horizon budget and staffing.")
    parser.add_argument("--scale", choices=SCALES, default="standard")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()

    cfg = SimConfig(scale=SCALES[args.scale], seed=args.seed)
    world = build_world(cfg)
    tables = build_budget_staffing(cfg, world)
    write_budget_staffing(tables, args.out)
    print(
        f"budget_rows={len(tables['fact_budget_quarterly']['region_id'])} "
        f"team_week_rows={len(tables['fact_team_week']['team_id'])}"
    )
    for line in crossing_summary(cfg, tables, world):
        print(line)


if __name__ == "__main__":
    main()

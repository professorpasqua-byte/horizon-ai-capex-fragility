"""Hourly infrastructure telemetry for Horizon: one row per cluster per hour.

What drives the numbers:
  - utilization follows the local day and week, grows over the year, and rises
    with AI demand once a region starts diverting budget
  - deferred maintenance builds up while the core budget is cut, and adds wear
  - wear and utilization raise temperature, which causes throttling
  - utilization above about 70 percent raises packet drops
  - latency follows a queueing curve, so it climbs slowly and then sharply

This module makes the baseline physical behaviour. Outages, monitoring gaps and
other mess are added by later steps.

Big tables here are dicts of numpy arrays. The deferred maintenance index is
latent (the cause, not something a company would measure), so it is written
to data/truth and never sits in the observed table.
"""

import argparse
from datetime import timedelta
from pathlib import Path

import numpy as np

from horizon.config import REGIONS, SCALES, WINDOW_START, SimConfig
from horizon.simulate.budget_staffing import (
    AI_DEMAND_FACTOR,
    BASE_CORE_SHARE,
    YEARLY_DEMAND_GROWTH,
    diversion_share,
    n_weeks,
    quarter_index,
)
from horizon.simulate.world import build_world

HOURS_PER_WEEK = 168
# How fast deferred maintenance builds: weekly increment is
# (diversion share / core share) / MAINTENANCE_WEEKS_TO_FULL.
MAINTENANCE_WEEKS_TO_FULL = 26.0
TEMP_THROTTLE_START_C = 75.0
TEMP_THROTTLE_SPAN_C = 15.0
MAX_UTIL = 0.985


def region_week_diversion(cfg: SimConfig) -> np.ndarray:
    """Array (regions, weeks) of the AI diversion share."""
    weeks = n_weeks(cfg)
    out = np.zeros((len(REGIONS), weeks))
    for r in range(len(REGIONS)):
        for w in range(weeks):
            wk = WINDOW_START.date() + timedelta(weeks=w)
            out[r, w] = diversion_share(r, quarter_index(wk))
    return out


def deferred_maintenance(diversion: np.ndarray) -> np.ndarray:
    """Cumulative deferred maintenance index per region and week."""
    return np.cumsum(diversion / BASE_CORE_SHARE / MAINTENANCE_WEEKS_TO_FULL, axis=1)


def build_telemetry(cfg: SimConfig, world: dict | None = None) -> dict:
    world = world or build_world(cfg)
    rng = np.random.default_rng(np.random.SeedSequence(cfg.seed).spawn(4)[3])

    clusters = world["dim_cluster"]
    regions = world["dim_region"]
    cluster_id = np.array(clusters["cluster_id"])
    region_idx = np.array(clusters["region_id"])
    age = np.array(clusters["hardware_age_years"])
    offset = np.array(regions["utc_offset_hours"])[region_idx]
    n_c, hours = len(cluster_id), cfg.hours
    weeks = n_weeks(cfg)

    diversion = region_week_diversion(cfg)
    debt = deferred_maintenance(diversion)

    h = np.arange(hours)
    week_of_hour = np.minimum(h // HOURS_PER_WEEK, weeks - 1)
    d_hour = diversion[region_idx][:, week_of_hour]
    debt_hour = debt[region_idx][:, week_of_hour]

    # Utilization: local daily wave, weekend dip, yearly growth, AI demand.
    local = (h[None, :] + offset[:, None]) % 24
    dow = (WINDOW_START.weekday() + (h[None, :] + offset[:, None]) // 24) % 7
    weekend = np.where(dow >= 5, 0.92, 1.0)
    diurnal = 0.12 * np.sin(2 * np.pi * (local - 9) / 24)
    base = rng.uniform(0.40, 0.60, n_c)[:, None]
    growth = 1 + YEARLY_DEMAND_GROWTH * h[None, :] / 8760
    shocks = rng.normal(0, 0.02, (n_c, hours))
    ar = np.zeros((n_c, hours))
    ar[:, 0] = shocks[:, 0]
    for t in range(1, hours):
        ar[:, t] = 0.8 * ar[:, t - 1] + shocks[:, t]
    util = (base + diurnal) * weekend * growth * (1 + AI_DEMAND_FACTOR * d_hour) + ar
    util = np.clip(util, 0.03, MAX_UTIL)

    wear = 0.5 * age[:, None] / 7.0 + debt_hour
    temp = 40 + 30 * util + 25 * wear + rng.normal(0, 1.5, (n_c, hours))
    throttle = 100 * np.clip((temp - TEMP_THROTTLE_START_C) / TEMP_THROTTLE_SPAN_C, 0, 1)
    drop = (0.02 + 6 * np.maximum(0, util - 0.7) ** 2 + 0.05 * wear) * np.exp(
        rng.normal(0, 0.3, (n_c, hours))
    )
    u_eff = np.minimum(MAX_UTIL, util / (1 - 0.5 * throttle / 100))
    latency = (18 + 12 * u_eff / (1 - u_eff)) * np.exp(rng.normal(0, 0.15, (n_c, hours)))

    start = np.datetime64(WINDOW_START.replace(tzinfo=None), "us")
    ts = start + (h * 3600 * 1_000_000).astype("timedelta64[us]")

    observed = {
        "cluster_id": np.repeat(cluster_id, hours),
        "hour_index": np.tile(h, n_c),
        "ts_utc": np.tile(ts, n_c),
        "cpu_util_pct": np.round(util * 100, 2).ravel(),
        "inlet_temp_c": np.round(temp, 2).ravel(),
        "throttle_pct": np.round(throttle, 2).ravel(),
        "packet_drop_pct": np.round(drop, 4).ravel(),
        "p99_latency_ms": np.round(latency, 2).ravel(),
    }
    latent = {
        "region_id": np.repeat(np.arange(len(REGIONS)), weeks),
        "week_index": np.tile(np.arange(weeks), len(REGIONS)),
        "deferred_maintenance_index": np.round(debt, 5).ravel(),
    }
    return {"fact_cluster_hour": observed, "latent_maintenance_week": latent}


def write_telemetry(tables: dict, root: Path = Path("data")) -> None:
    import polars as pl

    for name, sub in (
        ("fact_cluster_hour", "raw/telemetry"),
        ("latent_maintenance_week", "truth"),
    ):
        folder = root / sub
        folder.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(tables[name]).write_parquet(folder / f"{name}.parquet")


def summary(cfg: SimConfig, tables: dict, world: dict) -> list[str]:
    """Mean utilization, throttling and latency per region, first vs last quarter."""
    t = tables["fact_cluster_hour"]
    region_of = dict(zip(world["dim_cluster"]["cluster_id"], world["dim_cluster"]["region_id"]))
    reg = np.array([region_of[c] for c in t["cluster_id"]])
    q = t["hour_index"] // (cfg.hours // 4)
    lines = []
    for r, (name, _, _) in enumerate(REGIONS):
        parts = []
        for label, qq in (("Q0", 0), ("Q3", 3)):
            m = (reg == r) & (q == qq)
            parts.append(
                f"{label}: util {t['cpu_util_pct'][m].mean():.0f}% "
                f"throttle {t['throttle_pct'][m].mean():.1f}% "
                f"p99 {t['p99_latency_ms'][m].mean():.0f}ms"
            )
        lines.append(f"{name:14s} " + " | ".join(parts))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Horizon hourly telemetry.")
    parser.add_argument("--scale", choices=SCALES, default="standard")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()

    cfg = SimConfig(scale=SCALES[args.scale], seed=args.seed)
    world = build_world(cfg)
    tables = build_telemetry(cfg, world)
    write_telemetry(tables, args.out)
    print(f"cluster_hour_rows={len(tables['fact_cluster_hour']['cluster_id']):,}")
    for line in summary(cfg, tables, world):
        print(line)


if __name__ == "__main__":
    main()

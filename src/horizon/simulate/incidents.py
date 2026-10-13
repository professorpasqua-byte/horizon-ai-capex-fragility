"""Incidents, tickets and post-mortems for Horizon.

The hidden rules planted here (values live in HiddenTruth):
  - Incident hazard ramps up once a team's capacity-to-load ratio falls below
    the fracture ratio. The ramp is a hinge: zero at the fracture ratio and
    full strength one ramp width lower.
  - The hazard responds to the ratio from lag_weeks earlier, not today's.
  - Physical wear (deferred maintenance) also raises hazard. That is a real
    competing cause, so a method has to separate it from team strain.
  - Under strain, incidents get longer, more severe, and more often caused
    by process errors than by hardware.
  - Teams with low latent psychological safety fail to file a ticket for a
    larger share of real incidents (0.35 against 0.05). Post-mortems follow
    tickets, so unticketed incidents never get one.

Observed tables: fact_ticket, fact_postmortem. Answer key: latent_incident.
The overlay function stamps incidents onto telemetry (latency spikes, failed
health checks), which is how system monitoring still sees unticketed outages.
"""

import argparse
from pathlib import Path

import numpy as np

from horizon.config import REGIONS, SCALES, WINDOW_START, HiddenTruth, SimConfig
from horizon.simulate.budget_staffing import build_budget_staffing, n_weeks
from horizon.simulate.telemetry import (
    HOURS_PER_WEEK,
    deferred_maintenance,
    region_week_diversion,
)
from horizon.simulate.world import build_world

BASE_INCIDENT_RATE = 0.10  # incidents per cluster per week when nothing is wrong
STRAIN_MULTIPLIER = 5.0  # extra hazard at full ramp: rate x (1 + 5)
PHYSICAL_SENSITIVITY = 1.0  # hazard x (1 + this x deferred maintenance)
ROUTINE_TICKETS_PER_CLUSTER_DAY = 0.6
POSTMORTEM_PROB = 0.85
SEV_BASE = np.array([0.55, 0.30, 0.12, 0.03])
SEV_SHIFT = np.array([-0.25, -0.05, 0.17, 0.13])  # moves toward severe, sums to zero

_US_PER_HOUR = 3_600_000_000
_US_PER_MIN = 60_000_000


def ramp(ratio, truth: HiddenTruth):
    """0 at or above the fracture ratio, 1 one ramp width below it."""
    return np.clip((truth.fracture_ratio - np.asarray(ratio)) / truth.ramp_width, 0.0, 1.0)


def lag_series(x: np.ndarray, lag: int) -> np.ndarray:
    """Shift a (..., weeks) array later by lag weeks, padding with the first value."""
    n = x.shape[-1]
    lag = min(lag, n)
    if lag <= 0:
        return x
    pad = np.repeat(x[..., :1], lag, axis=-1)
    return np.concatenate([pad, x[..., : n - lag]], axis=-1)


def incident_rate(ratio, debt, truth: HiddenTruth):
    """Weekly incidents per cluster, and the ramp that produced them."""
    r = ramp(lag_series(np.asarray(ratio), truth.lag_weeks), truth)
    rate = BASE_INCIDENT_RATE * (1 + PHYSICAL_SENSITIVITY * debt) * (1 + STRAIN_MULTIPLIER * r)
    return rate, r


def _ts(hour_index: np.ndarray) -> np.ndarray:
    start = np.datetime64(WINDOW_START.replace(tzinfo=None), "us")
    return start + (np.asarray(hour_index, dtype=np.int64) * _US_PER_HOUR).astype("timedelta64[us]")


def build_incidents(cfg: SimConfig, world: dict, staffing: dict) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence(cfg.seed).spawn(5)[4])
    truth = cfg.truth
    H, W = cfg.hours, n_weeks(cfg)

    teams, clusters = world["dim_team"], world["dim_cluster"]
    n_t = len(teams["team_id"])
    team_region = np.array(teams["region_id"])
    c_id = np.array(clusters["cluster_id"])
    c_team = np.array(clusters["team_id"])
    c_region = np.array(clusters["region_id"])
    n_c = len(c_id)
    safety = np.array([world["truth"]["latent_safety_by_team"][str(t)] for t in teams["team_id"]])

    lat = staffing["latent_team_week"]
    ratio = np.zeros((n_t, W))
    load = np.zeros((n_t, W))
    for t, w, r, ld in zip(
        lat["team_id"], lat["week_index"], lat["capacity_load_ratio"], lat["load_units"]
    ):
        ratio[t, w] = r
        load[t, w] = ld

    debt = deferred_maintenance(region_week_diversion(cfg))
    rate, ramp_tw = incident_rate(ratio, debt[team_region], truth)

    # Incidents
    counts = rng.poisson(rate[c_team])
    flat = np.repeat(np.arange(n_c * W), counts.ravel())
    ci, wi = flat // W, flat % W
    start_hour = wi * HOURS_PER_WEEK + rng.integers(0, HOURS_PER_WEEK, len(flat))
    keep = start_hour < H
    ci, wi, start_hour = ci[keep], wi[keep], start_hour[keep]
    order = np.argsort(start_hour, kind="stable")
    ci, wi, start_hour = ci[order], wi[order], start_hour[order]
    n_i = len(ci)

    team_i = c_team[ci]
    ramp_i = ramp_tw[team_i, wi]
    duration = np.ceil(rng.lognormal(0.6, 0.7, n_i) * (1 + 1.5 * ramp_i)).astype(int)
    duration = np.clip(duration, 1, 48)
    probs = SEV_BASE[None, :] + ramp_i[:, None] * SEV_SHIFT[None, :]
    severity = 1 + (rng.random(n_i)[:, None] > np.cumsum(probs, axis=1)).sum(axis=1)
    physical = rng.random(n_i) < (0.7 - 0.3 * ramp_i)
    cause = np.where(physical, "hardware", "process")
    underreport = np.where(
        safety[team_i] < truth.low_safety_cutoff,
        truth.underreport_low_safety,
        truth.underreport_high_safety,
    )
    ticketed = rng.random(n_i) >= underreport

    # Tickets for filed incidents
    inc_idx = np.flatnonzero(ticketed)
    n_tk = len(inc_idx)
    start_ts = _ts(start_hour[inc_idx])
    end_of_window = _ts(np.array([H]))[0]
    created_inc = start_ts + (rng.integers(5, 180, n_tk) * _US_PER_MIN).astype("timedelta64[us]")
    created_inc = np.minimum(created_inc, end_of_window - np.timedelta64(1, "m"))
    resolved_inc = (
        _ts(start_hour[inc_idx] + duration[inc_idx])
        + (rng.integers(30, 720, n_tk) * _US_PER_MIN).astype("timedelta64[us]")
    )

    # Routine tickets: volume follows demand, resolution slows as strain grows
    days = cfg.scale.days
    day_week = np.minimum(np.arange(days) // 7, W - 1)
    load_rel = load / load[:, :1]
    lam = ROUTINE_TICKETS_PER_CLUSTER_DAY * load_rel[c_team][:, day_week]
    rc = rng.poisson(lam)
    r_flat = np.repeat(np.arange(n_c * days), rc.ravel())
    r_cluster, r_day = r_flat // days, r_flat % days
    n_r = len(r_flat)
    created_r = _ts(r_day * 24) + (rng.integers(0, 1440, n_r) * _US_PER_MIN).astype("timedelta64[us]")
    r_ratio = ratio[c_team[r_cluster], day_week[r_day]]
    res_hours = rng.lognormal(np.log(20), 0.6, n_r) / np.maximum(0.4, r_ratio) ** 2
    resolved_r = created_r + (res_hours * _US_PER_HOUR).astype("timedelta64[us]")

    # Combine, sort by time, assign ids
    created = np.concatenate([created_inc, created_r])
    resolved = np.concatenate([resolved_inc, resolved_r])
    resolved = np.where(resolved > end_of_window, np.datetime64("NaT"), resolved)
    t_team = np.concatenate([team_i[inc_idx], c_team[r_cluster]])
    t_cluster = np.concatenate([c_id[ci[inc_idx]], c_id[r_cluster]])
    t_type = np.concatenate([np.full(n_tk, "incident"), np.full(n_r, "routine")])
    t_sev = np.concatenate([severity[inc_idx], np.ones(n_r, dtype=int)])
    tk_order = np.argsort(created, kind="stable")
    rank = np.empty(len(created), dtype=int)
    rank[tk_order] = np.arange(len(created))

    fact_ticket = {
        "ticket_id": np.arange(1, len(created) + 1),
        "created_ts": created[tk_order],
        "team_id": t_team[tk_order],
        "cluster_id": t_cluster[tk_order],
        "ticket_type": t_type[tk_order],
        "severity": t_sev[tk_order],
        "resolved_ts": resolved[tk_order],
    }
    incident_ticket_id = np.full(n_i, -1)
    incident_ticket_id[inc_idx] = rank[:n_tk] + 1

    # Post-mortems: only for filed, resolved, severe incidents
    resolved_filed = resolved[:n_tk]
    pm_pick = (
        (severity[inc_idx] >= 3)
        & ~np.isnat(resolved_filed)
        & (rng.random(n_tk) < POSTMORTEM_PROB)
    )
    pm_ticket = rank[:n_tk][pm_pick] + 1
    pm_written = resolved_filed[pm_pick] + (
        rng.integers(1, 6, pm_pick.sum()) * 24 * _US_PER_HOUR
    ).astype("timedelta64[us]")
    pm_order = np.argsort(pm_ticket)
    fact_postmortem = {
        "postmortem_id": np.arange(1, pm_pick.sum() + 1),
        "ticket_id": pm_ticket[pm_order],
        "written_ts": pm_written[pm_order],
        "root_cause": cause[inc_idx][pm_pick][pm_order],
    }

    latent_incident = {
        "incident_id": np.arange(1, n_i + 1),
        "cluster_id": c_id[ci],
        "team_id": team_i,
        "region_id": c_region[ci],
        "week_index": wi,
        "start_hour_index": start_hour,
        "duration_hours": duration,
        "severity": severity,
        "cause": cause,
        "ramp_at_incident": np.round(ramp_i, 4),
        "team_safety": np.round(safety[team_i], 4),
        "ticketed": ticketed.astype(np.int8),
        "ticket_id": incident_ticket_id,
    }
    return {
        "fact_ticket": fact_ticket,
        "fact_postmortem": fact_postmortem,
        "latent_incident": latent_incident,
    }


def overlay_incidents(telemetry: dict, latent_incident: dict, cfg: SimConfig) -> dict:
    """Stamp incidents onto telemetry. Returns a copy with health_check_ok added."""
    H = cfg.hours
    out = {k: v.copy() for k, v in telemetry.items()}
    health = np.ones(len(out["cluster_id"]), dtype=np.int8)
    for c, s, d, sev in zip(
        latent_incident["cluster_id"],
        latent_incident["start_hour_index"],
        latent_incident["duration_hours"],
        latent_incident["severity"],
    ):
        a, b = int(c) * H + int(s), int(c) * H + min(int(s) + int(d), H)
        out["p99_latency_ms"][a:b] = np.round(out["p99_latency_ms"][a:b] * (2.0 * sev + 2.0), 2)
        out["packet_drop_pct"][a:b] = np.round(out["packet_drop_pct"][a:b] + 0.5 * sev, 4)
        if sev >= 2:
            health[a:b] = 0
    out["health_check_ok"] = health
    return out


def write_incidents(tables: dict, root: Path = Path("data")) -> None:
    import polars as pl

    for name, sub in (
        ("fact_ticket", "raw/tickets"),
        ("fact_postmortem", "raw/tickets"),
        ("latent_incident", "truth"),
    ):
        folder = root / sub
        folder.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(tables[name]).write_parquet(folder / f"{name}.parquet")


def summary(cfg: SimConfig, tables: dict) -> list[str]:
    inc = tables["latent_incident"]
    tk = tables["fact_ticket"]
    lines = [
        f"incidents={len(inc['incident_id'])} "
        f"incident_tickets={int((tk['ticket_type'] == 'incident').sum())} "
        f"routine_tickets={int((tk['ticket_type'] == 'routine').sum())} "
        f"postmortems={len(tables['fact_postmortem']['postmortem_id'])}"
    ]
    low = inc["team_safety"] < cfg.truth.low_safety_cutoff
    for label, m in (("low safety ", low), ("high safety", ~low)):
        lines.append(
            f"{label}: incidents {int(m.sum()):3d}  ticketed share {inc['ticketed'][m].mean():.2f}"
        )
    for r, (name, _, _) in enumerate(REGIONS):
        m = inc["region_id"] == r
        lines.append(f"{name:14s} incidents {int(m.sum()):3d}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Horizon incidents and tickets.")
    parser.add_argument("--scale", choices=SCALES, default="standard")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()

    cfg = SimConfig(scale=SCALES[args.scale], seed=args.seed)
    world = build_world(cfg)
    staffing = build_budget_staffing(cfg, world)
    tables = build_incidents(cfg, world, staffing)
    write_incidents(tables, args.out)
    for line in summary(cfg, tables):
        print(line)


if __name__ == "__main__":
    main()

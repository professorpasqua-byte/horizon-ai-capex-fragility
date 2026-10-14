"""Turn the clean Horizon world into the messy extracts a pipeline would receive.

data/raw holds the clean originals (used only to grade the cleaning step).
data/landing holds what each source system actually hands over. The pipeline
may only read data/landing.

Each source has its own pace and its own flaws:
  telemetry   near real time, readings drop and repeat, one region logs local
              time as if it were UTC, outages also silence the monitors,
              -999 sentinels, some readings arrive hours late
  staffing    weekly HR export delivered days later, inconsistent team labels,
              missing weeks, restated rows, -1 sentinels
  budget      quarterly, money stored as text, some quarters restated later
  tickets     daily batch, one region in local time with an offset, repeats,
              blank severities
  postmortems written days after the incident, free-text cause labels
  survey      monthly pulse, small teams suppressed, scores are noisy

latent_mess_ledger records what was injected so quality checks can be graded.
"""

import argparse
import re
from pathlib import Path

import numpy as np

from horizon.config import REGIONS, SCALES, SimConfig
from horizon.simulate.budget_staffing import build_budget_staffing
from horizon.simulate.incidents import build_incidents, overlay_incidents
from horizon.simulate.telemetry import build_telemetry
from horizon.simulate.world import build_world

_HOUR = 3_600_000_000
_DAY = 86_400_000_000

TZ_REGION = 2  # apac-south logs local time without a zone label
LOCAL_TICKET_REGION = 3  # latam-central tickets carry a local offset
DROP_RATE = 0.005
GAP_DROP = 0.60  # share of hours lost during severe incidents
DUP_RATE = 0.003
RESTATE_RATE = 0.002
SENTINEL_RATE = 0.002
LATE_RATE = 0.02
HR_MISSING = 0.03
HR_RESTATE = 0.02
HR_SENTINEL = 0.005
BUDGET_RESTATE = 0.40
TICKET_DUP = 0.01
SEVERITY_BLANK = 0.03
MIN_SURVEY_CELL = 5


def normalize_team_label(label: str) -> str:
    """Map any messy team label back to its canonical team_name."""
    return re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")


def _messy_label(name: str, variant: int) -> str:
    if variant == 0:
        return name
    if variant == 1:
        return name.upper().replace("-", "_")
    return " " + name.replace("-", " ").title() + " "


def _us(days=0.0, hours=0.0):
    return (np.asarray(days) * _DAY + np.asarray(hours) * _HOUR).astype("int64").astype("timedelta64[us]")


class Ledger:
    def __init__(self):
        self.rows = []

    def add(self, source, defect, rows, note):
        self.rows.append((source, defect, int(rows), note))

    def table(self):
        return {
            "source": np.array([r[0] for r in self.rows]),
            "defect": np.array([r[1] for r in self.rows]),
            "rows": np.array([r[2] for r in self.rows]),
            "note": np.array([r[3] for r in self.rows]),
        }


def _telemetry(cfg, world, tel, inc, rng, ledger):
    H = cfg.hours
    n = len(tel["cluster_id"])
    keep = np.ones(n, dtype=bool)

    gap = []
    for c, s, d, sev in zip(
        inc["cluster_id"], inc["start_hour_index"], inc["duration_hours"], inc["severity"]
    ):
        if sev >= 3:
            gap.extend(range(int(c) * H + int(s), int(c) * H + min(int(s) + int(d), H)))
    gap = np.unique(np.array(gap, dtype=int))
    gap_drop = gap[rng.random(len(gap)) < GAP_DROP]
    keep[gap_drop] = False
    rand_drop = (rng.random(n) < DROP_RATE) & keep
    keep &= ~rand_drop
    ledger.add("telemetry", "monitoring_gap", len(gap_drop), "hours lost during severity 3+ incidents")
    ledger.add("telemetry", "random_missing", rand_drop.sum(), "readings never delivered")

    s = cfg.scale.samples_per_hour
    rows = np.flatnonzero(keep)
    idx = np.repeat(rows, s)
    minute = np.tile((np.arange(s) * 60) // s, len(rows))
    cols = {
        k: tel[k][idx]
        for k in (
            "cluster_id",
            "cpu_util_pct",
            "inlet_temp_c",
            "throttle_pct",
            "packet_drop_pct",
            "p99_latency_ms",
            "health_check_ok",
        )
    }
    if s > 1:
        for k in ("cpu_util_pct", "inlet_temp_c", "packet_drop_pct", "p99_latency_ms"):
            cols[k] = np.round(cols[k] * (1 + rng.normal(0, 0.02, len(idx))), 3)
    N = len(idx)
    ts_true = tel["ts_utc"][idx] + _us(hours=minute / 60)
    ingested = ts_true + _us(hours=1 / s) + _us(days=rng.integers(30, 300, N) / 86400)

    sentinel = rng.random(N) < SENTINEL_RATE
    cols["inlet_temp_c"] = cols["inlet_temp_c"].copy()
    cols["inlet_temp_c"][sentinel] = -999.0
    ledger.add("telemetry", "sentinel_value", sentinel.sum(), "inlet_temp_c = -999")

    late = rng.random(N) < LATE_RATE
    ingested[late] += _us(hours=rng.uniform(1, 6, late.sum()))
    ledger.add("telemetry", "late_arrival", late.sum(), "delivered 1 to 6 hours late")

    region_of = np.array(world["dim_cluster"]["region_id"])[cols["cluster_id"]]
    shifted = region_of == TZ_REGION
    ts_reported = ts_true + _us(hours=np.where(shifted, REGIONS[TZ_REGION][1], 0))
    ledger.add("telemetry", "local_time_as_utc", shifted.sum(), "apac-south timestamps are local time")

    out = dict(cols, ts_reported=ts_reported, ingested_ts=ingested)
    dup = rng.random(N) < DUP_RATE
    res = rng.random(N) < RESTATE_RATE
    extra_dup = {k: v[dup] for k, v in out.items()}
    extra_dup["ingested_ts"] = extra_dup["ingested_ts"] + _us(hours=rng.uniform(1, 12, dup.sum()))
    extra_res = {k: v[res] for k, v in out.items()}
    extra_res["cpu_util_pct"] = np.round(extra_res["cpu_util_pct"] + rng.uniform(1, 3, res.sum()), 3)
    extra_res["p99_latency_ms"] = np.round(extra_res["p99_latency_ms"] * 1.05, 3)
    extra_res["ingested_ts"] = extra_res["ingested_ts"] + _us(hours=rng.uniform(1, 12, res.sum()))
    ledger.add("telemetry", "exact_duplicate", dup.sum(), "same reading delivered twice")
    ledger.add("telemetry", "restated_duplicate", res.sum(), "same key, changed values")

    merged = {k: np.concatenate([out[k], extra_dup[k], extra_res[k]]) for k in out}
    order = np.argsort(merged["ingested_ts"], kind="stable")
    return {k: v[order] for k, v in merged.items()}


def _staffing(world, f, rng, ledger):
    names = dict(zip(world["dim_team"]["team_id"], world["dim_team"]["team_name"]))
    team = np.array(f["team_id"])
    week_end = np.array(f["week_start"], dtype="datetime64[D]") + np.timedelta64(6, "D")
    cols = {k: np.array(f[k]) for k in ("funded_headcount", "headcount", "hires", "departures", "reductions")}
    cols["overtime_hours_per_head"] = np.array(f["overtime_hours_per_head"], dtype=float)

    keep = rng.random(len(team)) >= HR_MISSING
    ledger.add("staffing", "missing_week", (~keep).sum(), "HR export skipped these team-weeks")
    team, week_end = team[keep], week_end[keep]
    cols = {k: v[keep] for k, v in cols.items()}
    sentinel = rng.random(len(team)) < HR_SENTINEL
    cols["overtime_hours_per_head"][sentinel] = -1.0
    ledger.add("staffing", "sentinel_value", sentinel.sum(), "overtime_hours_per_head = -1")

    variant = rng.integers(0, 3, len(team))
    label = np.array([_messy_label(names[int(t)], int(v)) for t, v in zip(team, variant)])
    delivered = week_end.astype("datetime64[us]") + _us(days=rng.integers(3, 11, len(team)), hours=6)
    base = dict(team_label=label, week_ending=week_end, **cols, delivered_at=delivered)

    res = rng.random(len(team)) < HR_RESTATE
    extra = {k: v[res].copy() for k, v in base.items()}
    bump = rng.choice([-1, 1], res.sum())
    extra["headcount"] = np.maximum(2, extra["headcount"] + bump)
    extra["delivered_at"] = extra["delivered_at"] + _us(days=rng.integers(7, 15, res.sum()))
    ledger.add("staffing", "restated_row", res.sum(), "same team-week resent with a changed headcount")
    return {k: np.concatenate([base[k], extra[k]]) for k in base}


def _budget(world, b, rng, ledger):
    region_name = dict(zip(world["dim_region"]["region_id"], world["dim_region"]["region_name"]))
    out = {k: [] for k in (
        "region_name", "fiscal_quarter", "quarter_start", "version",
        "total_budget", "ai_budget", "core_budget", "ai_share", "delivered_at",
    )}

    def add(i, version, core, delivered_days):
        name = region_name[b["region_id"][i]]
        out["region_name"].append([name, name.upper(), name.replace("-", " ").title()][int(rng.integers(0, 3))])
        out["fiscal_quarter"].append(f"FY26-Q{b['quarter'][i] + 1}")
        out["quarter_start"].append(np.datetime64(b["quarter_start"][i], "D"))
        out["version"].append(version)
        out["total_budget"].append(f"${b['total_budget_musd'][i]:.2f}M")
        out["ai_budget"].append(f"${b['ai_budget_musd'][i]:.2f}M")
        out["core_budget"].append(f"${core:.2f}M")
        out["ai_share"].append(f"{b['ai_diversion_share'][i] * 100:.1f}%")
        out["delivered_at"].append(np.datetime64(b["quarter_start"][i], "us") + _us(days=delivered_days))

    restated = 0
    for i in range(len(b["region_id"])):
        add(i, 1, b["core_budget_musd"][i], 10)
        if b["ai_diversion_share"][i] > 0 and rng.random() < BUDGET_RESTATE:
            add(i, 2, b["core_budget_musd"][i] * (1 + rng.uniform(-0.02, 0.02)), 45)
            restated += 1
    ledger.add("budget", "restated_quarter", restated, "version 2 rows with revised core budget")
    ledger.add("budget", "money_as_text", len(out["version"]), "amounts stored like $12.50M")
    return {
        k: np.array(v, dtype="datetime64[us]" if k == "delivered_at" else None) if k != "version" else np.array(v)
        for k, v in out.items()
    }


def _ts_text(ts, suffix):
    text = np.char.add(np.datetime_as_string(ts, unit="s"), suffix)
    return np.where(np.isnat(ts), "", text)


def _tickets(world, tk, rng, ledger):
    team_region = dict(zip(world["dim_team"]["team_id"], world["dim_team"]["region_id"]))
    reg = np.array([team_region[int(t)] for t in tk["team_id"]])
    local = reg == LOCAL_TICKET_REGION
    off = REGIONS[LOCAL_TICKET_REGION][1]
    shift = _us(hours=np.where(local, off, 0))
    suffix = np.where(local, f"{off:+03d}:00", "Z")
    created, resolved = tk["created_ts"], tk["resolved_ts"]
    ledger.add("tickets", "local_time_with_offset", local.sum(), "latam-central timestamps carry -03:00")

    severity = tk["severity"].astype(float)
    blank = (tk["ticket_type"] == "routine") & (rng.random(len(severity)) < SEVERITY_BLANK)
    severity[blank] = np.nan
    ledger.add("tickets", "blank_severity", blank.sum(), "routine tickets with no severity")

    last = np.where(np.isnat(resolved), created, resolved)
    delivered = last.astype("datetime64[D]").astype("datetime64[us]") + _us(hours=26)
    base = {
        "ticket_id": tk["ticket_id"],
        "created_ts": _ts_text(created + shift, suffix),
        "team_id": tk["team_id"],
        "cluster_id": tk["cluster_id"],
        "ticket_type": tk["ticket_type"],
        "severity": severity,
        "resolved_ts": _ts_text(resolved + shift, suffix),
        "delivered_at": delivered,
    }
    dup = rng.random(len(severity)) < TICKET_DUP
    extra = {k: v[dup].copy() for k, v in base.items()}
    extra["delivered_at"] = extra["delivered_at"] + _us(days=1)
    ledger.add("tickets", "exact_duplicate", dup.sum(), "ticket exported twice")
    return {k: np.concatenate([base[k], extra[k]]) for k in base}


def _postmortems(pm, rng, ledger):
    options = {
        "hardware": ["hardware", "Hardware", "HW failure", "hardware fault"],
        "process": ["process", "Process", "process error", "human error"],
    }
    label = np.array([options[c][int(rng.integers(0, 4))] for c in pm["root_cause"]])
    ledger.add("postmortems", "free_text_cause", len(label), "root cause typed in free text")
    return {
        "ticket_id": pm["ticket_id"],
        "written_ts": pm["written_ts"],
        "root_cause": label,
        "delivered_at": pm["written_ts"] + _us(days=1),
    }


def _survey(world, f, rng, ledger):
    safety = world["truth"]["latent_safety_by_team"]
    names = dict(zip(world["dim_team"]["team_id"], world["dim_team"]["team_name"]))
    team = np.array(f["team_id"])
    month = np.array(f["week_start"], dtype="datetime64[D]").astype("datetime64[M]")
    hc = np.array(f["headcount"], dtype=float)
    ot = np.array(f["overtime_hours_per_head"], dtype=float)
    out = {k: [] for k in ("team_label", "month_start", "invited", "responses", "mean_safety_score", "delivered_at")}
    suppressed = 0
    for t in np.unique(team):
        for m in np.unique(month):
            sel = (team == t) & (month == m)
            if not sel.any():
                continue
            invited = int(round(hc[sel].mean()))
            rate = float(np.clip(0.85 - 0.02 * ot[sel].mean(), 0.2, 0.95))
            n = int(rng.binomial(invited, rate))
            if n < MIN_SURVEY_CELL:
                score = np.nan
                suppressed += 1
            else:
                score = float(np.clip(1 + 4 * safety[str(int(t))] + rng.normal(0, 0.7 / np.sqrt(n)), 1, 5))
            out["team_label"].append(_messy_label(names[int(t)], int(rng.integers(0, 3))))
            out["month_start"].append(m.astype("datetime64[D]"))
            out["invited"].append(invited)
            out["responses"].append(n)
            out["mean_safety_score"].append(round(score, 3) if n >= MIN_SURVEY_CELL else np.nan)
            out["delivered_at"].append((m + np.timedelta64(1, "M")).astype("datetime64[D]").astype("datetime64[us]") + _us(days=5))
    ledger.add("survey", "suppressed_small_cell", suppressed, f"fewer than {MIN_SURVEY_CELL} responses, score hidden")
    return {k: np.array(v) for k, v in out.items()}


def build_landing(cfg: SimConfig, world=None, staffing=None, telemetry=None, incidents=None) -> dict:
    world = world or build_world(cfg)
    staffing = staffing or build_budget_staffing(cfg, world)
    telemetry = telemetry or build_telemetry(cfg, world)
    incidents = incidents or build_incidents(cfg, world, staffing)
    inc = incidents["latent_incident"]
    tel = overlay_incidents(telemetry["fact_cluster_hour"], inc, cfg)

    rng = np.random.default_rng(np.random.SeedSequence(cfg.seed).spawn(6)[5])
    ledger = Ledger()
    landing = {
        "telemetry": _telemetry(cfg, world, tel, inc, rng, ledger),
        "staffing": _staffing(world, staffing["fact_team_week"], rng, ledger),
        "budget": _budget(world, staffing["fact_budget_quarterly"], rng, ledger),
        "tickets": _tickets(world, incidents["fact_ticket"], rng, ledger),
        "postmortems": _postmortems(incidents["fact_postmortem"], rng, ledger),
        "survey": _survey(world, staffing["fact_team_week"], rng, ledger),
    }
    landing["latent_mess_ledger"] = ledger.table()
    return landing


def write_landing(landing: dict, root: Path = Path("data")) -> None:
    import polars as pl

    (root / "landing").mkdir(parents=True, exist_ok=True)
    (root / "truth").mkdir(parents=True, exist_ok=True)
    for name, table in landing.items():
        folder = root / ("truth" if name.startswith("latent_") else "landing")
        pl.DataFrame(table).write_parquet(folder / f"{name}.parquet")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the messy Horizon landing files.")
    parser.add_argument("--scale", choices=SCALES, default="standard")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()

    cfg = SimConfig(scale=SCALES[args.scale], seed=args.seed)
    landing = build_landing(cfg)
    write_landing(landing, args.out)
    for name, table in landing.items():
        if not name.startswith("latent_"):
            print(f"{name:12s} rows={len(next(iter(table.values()))):,}")
    led = landing["latent_mess_ledger"]
    for s, d, r in zip(led["source"], led["defect"], led["rows"]):
        print(f"  {s}.{d}: {r:,}")


if __name__ == "__main__":
    main()

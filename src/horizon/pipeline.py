"""Run bronze -> silver -> gold, check every layer, read and write the files.

Reads data/landing (messy sources) and data/raw/dims (reference tables).
Never reads data/truth.
"""

import argparse
import csv
from pathlib import Path

import numpy as np

from horizon.bronze.ingest import to_bronze
from horizon.gold.build import HPW, build_gold
from horizon.silver.clean import clean_all


def _rows(table):
    return len(next(iter(table.values())))


def run_checks(bronze, silver, gold, dims):
    checks = []

    def add(layer, name, passed, detail=""):
        checks.append((layer, name, bool(passed), str(detail)))

    for name, t in bronze.items():
        add("bronze", f"{name}_rows_present", _rows(t) > 0, _rows(t))
    t = silver["telemetry"]
    pairs = t["cluster_id"].astype("int64") * 10**12 + t["ts_utc"].astype("int64") // 10**6
    add("silver", "telemetry_no_duplicate_keys", len(np.unique(pairs)) == len(pairs))
    add("silver", "telemetry_no_sentinels", not (t["inlet_temp_c"] == -999).any())
    share = float((t["ts_utc"] <= t["ingested_ts"]).mean())
    add("silver", "telemetry_not_from_the_future", share > 0.999, f"{share:.4f}")
    add("silver", "ticket_ids_unique", len(np.unique(silver["tickets"]["ticket_id"])) == _rows(silver["tickets"]))
    tk = silver["tickets"]
    done = ~np.isnat(tk["resolved_utc"])
    add("silver", "tickets_resolve_after_creation", (tk["resolved_utc"][done] >= tk["created_utc"][done]).all())
    add("silver", "budget_amounts_positive", (silver["budget"]["total_budget_musd"] > 0).all())
    add("silver", "staffing_one_current_per_week", silver["staffing"]["is_current"].sum() ==
        len(np.unique(silver["staffing"]["team_id"] * 100000 + silver["staffing"]["week_ending"].astype("int64"))))
    ch, tw = gold["gold_cluster_hour"], gold["gold_team_week"]
    n_c, n_t = len(dims["dim_cluster"]["cluster_id"]), len(dims["dim_team"]["team_id"])
    hours = _rows(ch) // n_c
    add("gold", "cluster_hour_grid_complete", _rows(ch) == n_c * hours, f"{_rows(ch):,} rows")
    add("gold", "team_week_grid_complete", _rows(tw) == n_t * (hours // HPW), f"{_rows(tw):,} rows")
    cov = float((ch["reading_count"] > 0).mean())
    add("gold", "telemetry_coverage_in_range", 0.95 < cov < 1.0, f"{cov:.4f}")
    first_known = float(np.isnan(ch["headcount_known"]).mean())
    add("gold", "staffing_known_after_first_delivery", first_known < 0.06, f"{first_known:.4f} unknown (first deliveries lag the window start)")
    return checks


def run_pipeline(landing, dims):
    bronze = to_bronze({k: v for k, v in landing.items() if not k.startswith("latent_")})
    silver, dq = clean_all(bronze, dims)
    gold = build_gold(silver, dims)
    return bronze, silver, gold, dq, run_checks(bronze, silver, gold, dims)


def read_table(path):
    import polars as pl

    out = {}
    for c, s in pl.read_parquet(path).to_dict(as_series=True).items():
        a = s.to_numpy()
        out[c] = a.astype(str) if a.dtype == object else a
    return out


def main():
    import polars as pl

    parser = argparse.ArgumentParser(description="Run the Horizon pipeline.")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    args = parser.parse_args()

    landing = {p.stem: read_table(p) for p in sorted((args.root / "landing").glob("*.parquet"))}
    dims = {p.stem: read_table(p) for p in sorted((args.root / "raw" / "dims").glob("*.parquet"))}
    bronze, silver, gold, dq, checks = run_pipeline(landing, dims)

    for layer, tables in (("silver", silver), ("gold", gold)):
        folder = args.root / layer
        folder.mkdir(parents=True, exist_ok=True)
        for name, t in tables.items():
            pl.DataFrame(t).write_parquet(folder / f"{name}.parquet")
    args.results.mkdir(parents=True, exist_ok=True)
    for fname, rows, header in (
        ("dq_report.csv", checks, ["layer", "check", "passed", "detail"]),
        ("cleaning_report.csv", dq, ["source", "action", "value"]),
    ):
        with open(args.results / fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    for source, action, value in dq:
        print(f"  {source}.{action}: {value}")
    for layer, name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {layer}.{name} {detail}")
    print(f"gold_cluster_hour rows={_rows(gold['gold_cluster_hour']):,}  gold_team_week rows={_rows(gold['gold_team_week']):,}")


if __name__ == "__main__":
    main()

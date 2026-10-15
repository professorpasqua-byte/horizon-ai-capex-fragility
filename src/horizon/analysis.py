"""Run the three models on the gold tables, grade them, write small result files."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from horizon.grading.grade import grade, summarize
from horizon.models.early_warning import early_warning
from horizon.models.features import capacity_index
from horizon.models.hinge import fit_tipping_point
from horizon.models.reporting_gap import reporting_gap


def analyze(gold, tickets, dims, hours):
    tw, ch = gold["gold_team_week"], gold["gold_cluster_hour"]
    exposure = np.bincount(np.asarray(dims["dim_cluster"]["team_id"]))[tw["team_id"]].astype(float)
    tip = fit_tipping_point(tw, exposure)
    return {
        "tipping": tip,
        "tipping_tickets_only": fit_tipping_point(tw, exposure, "incident_tickets"),
        "early": early_warning(tw, tip["knot"]),
        "gap": reporting_gap(ch, tickets, tw, hours),
    }


def _py(x):
    if isinstance(x, dict):
        return {k: _py(v) for k, v in x.items() if not k.startswith("profile")}
    if isinstance(x, (list, tuple)):
        return [_py(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_py(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        return None if np.isnan(x) else round(float(x), 4)
    if isinstance(x, (np.integer, np.bool_)):
        return x.item()
    return x


def write_csv(path, table):
    cols = list(table)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in zip(*[np.asarray(table[c]).tolist() for c in cols]):
            w.writerow([("" if isinstance(v, float) and np.isnan(v) else (round(v, 4) if isinstance(v, float) else v)) for v in row])


def write_results(result, rows, tw, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    findings = _py({k: v for k, v in result.items()})
    findings["grading"] = summarize(rows)
    (out / "findings.json").write_text(json.dumps(findings, indent=2))
    write_csv(out / "grading.csv", {k: [r[k] for r in rows] for k in rows[0]})
    tip = result["tipping"]
    write_csv(out / "tipping_profile.csv", {"knot": tip["profile_knots"], "loglik_drop": tip["profile_ll"]})
    write_csv(out / "lead_time_profile.csv", {"lag_weeks": tip["profile_lags"], "loglik_drop": tip["profile_lag_ll"]})
    write_csv(out / "early_warning.csv", result["early"])
    g = result["gap"]
    write_csv(out / "reporting_gap.csv", {k: g[k] for k in ("team_id", "episodes", "ticketed", "filing_rate", "safety_score", "low_safety")})
    signals = {k: tw[k] for k in (
        "team_id", "region_id", "week_index", "headcount", "overtime_hours_per_head", "open_backlog_end",
        "detected_outage_episodes", "incident_tickets", "mean_p99_latency_ms", "safety_known", "ai_share_known")}
    signals["capacity_index"] = capacity_index(tw)
    write_csv(out / "team_signals.csv", signals)


def main():
    from horizon.pipeline import read_table

    parser = argparse.ArgumentParser(description="Run models and grade them.")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    args = parser.parse_args()
    root = args.root
    gold = {p.stem: read_table(p) for p in (root / "gold").glob("*.parquet")}
    tickets = read_table(root / "silver" / "tickets.parquet")
    dims = {p.stem: read_table(p) for p in (root / "raw" / "dims").glob("*.parquet")}
    hours = len(gold["gold_cluster_hour"]["cluster_id"]) // len(dims["dim_cluster"]["cluster_id"])
    result = analyze(gold, tickets, dims, hours)

    truth = json.loads((root / "truth" / "hidden_truth.json").read_text())
    latent = read_table(root / "truth" / "latent_team_week.parquet")
    led = read_table(root / "truth" / "latent_mess_ledger.parquet")
    ledger = {f"{s}.{d}": int(r) for s, d, r in zip(led["source"], led["defect"], led["rows"])}
    with open(args.results / "cleaning_report.csv") as f:
        cleaning = [(r["source"], r["action"], int(r["value"])) for r in csv.DictReader(f)]
    rows = grade(result, truth, latent, ledger, cleaning, dims)
    write_results(result, rows, gold["gold_team_week"], args.results)
    tip, gap = result["tipping"], result["gap"]
    print(f"tipping point index {tip['knot']} (CI {tip['knot_ci']}), lead time {tip['lag_weeks']} weeks (CI {tip['lag_ci']})")
    print(f"filing rate: low-safety teams {gap['low_rate']:.2f}, high-safety teams {gap['high_rate']:.2f}")
    for r in rows:
        print(f"{r['verdict'].upper():4s} {r['metric']}: found {r['found']} vs truth {r['truth']}")
    print(summarize(rows))


if __name__ == "__main__":
    main()

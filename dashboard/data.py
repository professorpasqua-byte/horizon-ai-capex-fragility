"""Small helpers the Streamlit pages use. Reads only results/*.csv and findings.json."""

import json
from pathlib import Path

import pandas as pd

RESULTS = Path(__file__).resolve().parents[1] / "results"
REGION_NAMES = {0: "na-east", 1: "eu-west", 2: "apac-south", 3: "latam-central"}
START_RATIO = 1.05  # true capacity-to-load ratio = 1.05 x the index the models can observe


def read_csv(name, results=RESULTS):
    return pd.read_csv(Path(results) / name)


def findings(results=RESULTS):
    return json.loads((Path(results) / "findings.json").read_text())


def headline(results=RESULTS):
    f, g = findings(results), read_csv("grading.csv", results)
    tip, gap = f["tipping"], f["gap"]
    truth = float(g.loc[g.metric == "tipping_point_ratio", "truth"].iloc[0])
    return {
        "tipping_ratio": round(tip["knot"] * START_RATIO, 2),
        "tipping_ci": tuple(round(v * START_RATIO, 2) for v in tip["knot_ci"]),
        "true_tipping_ratio": truth,
        "lag_weeks": tip["lag_weeks"], "lag_ci": tuple(tip["lag_ci"]),
        "low_rate": gap["low_rate"], "high_rate": gap["high_rate"],
        "rate_gap_ci": tuple(gap["rate_gap_ci"]),
        "episodes": gap["episodes_total"], "unticketed": gap["unticketed_total"],
        "hits": f["grading"]["hits"], "total": f["grading"]["total"], "misses": f["grading"]["misses"],
        "knot_index": tip["knot"],
    }


def region_index_by_week(results=RESULTS, with_knot=True):
    ts = read_csv("team_signals.csv", results)
    wide = ts.groupby(["week_index", "region_id"]).capacity_index.mean().unstack()
    wide.columns = [REGION_NAMES[c] for c in wide.columns]
    if with_knot:
        wide["tipping point"] = findings(results)["tipping"]["knot"]
    return wide


def episodes_by_region_week(results=RESULTS, window=4):
    """Detected outages per week by region, as a rolling average so the pattern is readable."""
    ts = read_csv("team_signals.csv", results)
    wide = ts.groupby(["week_index", "region_id"]).detected_outage_episodes.sum().unstack()
    wide.columns = [REGION_NAMES[c] for c in wide.columns]
    return wide.rolling(window, min_periods=1).mean()


def _fit(frame, column):
    p = frame.set_index(column).loglik_drop
    return (p - p.min()).rename("fit (higher is better)").to_frame()


def tipping_profile(results=RESULTS):
    return _fit(read_csv("tipping_profile.csv", results), "knot")


def lead_time_profile(results=RESULTS):
    return _fit(read_csv("lead_time_profile.csv", results), "lag_weeks")


def budget_view(results=RESULTS):
    """What teams looked like at each level of AI budget share (team-weeks)."""
    ts = read_csv("team_signals.csv", results).dropna(subset=["ai_share_known"])
    ts["ai_share"] = ts.ai_share_known.round(2)
    out = ts.groupby("ai_share").agg(
        capacity_index=("capacity_index", "mean"),
        outages_per_team_week=("detected_outage_episodes", "mean"),
        overtime_hours=("overtime_hours_per_head", "mean"),
        team_weeks=("team_id", "size"),
    )
    return out


def team_filing(results=RESULTS):
    return read_csv("reporting_gap.csv", results)

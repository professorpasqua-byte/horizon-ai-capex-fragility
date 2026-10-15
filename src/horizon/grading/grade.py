"""Grade the findings against the hidden truth, and say plainly where they miss.

Only this module and the analysis runner may read data/truth.
"""

import numpy as np

from horizon.config import REGIONS
from horizon.simulate.budget_staffing import START_RATIO
from horizon.simulate.incidents import STRAIN_MULTIPLIER

TOL = {"tipping": 0.05, "lag": 1, "rate": 0.10, "bias_weeks": 5}


def true_crossing_weeks(latent_team_week, fracture):
    team, week, ratio = (np.asarray(latent_team_week[k]) for k in ("team_id", "week_index", "capacity_load_ratio"))
    out = {}
    for t in np.unique(team):
        w = week[(team == t) & (ratio < fracture)]
        out[int(t)] = int(w.min()) if len(w) else -1
    return out


def _row(metric, found, truth, hit, note=""):
    err = found - truth if isinstance(found, (int, float, np.floating)) and isinstance(truth, (int, float, np.floating)) else ""
    return {"metric": metric, "found": found, "truth": truth, "error": err, "verdict": "hit" if hit else "miss", "note": note}


def grade(result, truth, latent_team_week, ledger, cleaning, dims):
    tip, ew, gap = result["tipping"], result["early"], result["gap"]
    rows = []
    fr = truth["fracture_ratio"]
    found = round(tip["knot"] * START_RATIO, 3)
    rows.append(_row("tipping_point_ratio", found, fr, abs(found - fr) <= TOL["tipping"],
                     "the model's hinge starts later than the planted one" if found > fr + TOL["tipping"]
                     else "the model's hinge starts earlier than the planted one" if found < fr - TOL["tipping"] else ""))
    lo, hi = tip["knot_ci"][0] * START_RATIO, tip["knot_ci"][1] * START_RATIO
    rows.append(_row("tipping_point_interval_covers_truth", f"{lo:.2f} to {hi:.2f}", fr, lo <= fr <= hi,
                     "interval is built on a proxy for workload, so it can be too narrow"))
    rows.append(_row("lead_time_weeks", tip["lag_weeks"], truth["lag_weeks"], abs(tip["lag_weeks"] - truth["lag_weeks"]) <= TOL["lag"]))
    rows.append(_row("lead_time_interval_covers_truth", f"{tip['lag_ci'][0]} to {tip['lag_ci'][1]}", truth["lag_weeks"],
                     tip["lag_ci"][0] <= truth["lag_weeks"] <= tip["lag_ci"][1]))
    planted = 1 + STRAIN_MULTIPLIER
    mult = round(tip["rate_multiplier_at_full_strain"], 2)
    rows.append(_row("outage_rate_multiplier", mult, planted, abs(mult / planted - 1) <= 0.5,
                     "a smooth curve is fitted to what is really a straight ramp"))

    rows.append(_row("filing_rate_low_safety_teams", round(gap["low_rate"], 3), round(1 - truth["underreport_low_safety"], 3),
                     abs(gap["low_rate"] - (1 - truth["underreport_low_safety"])) <= TOL["rate"]))
    rows.append(_row("filing_rate_high_safety_teams", round(gap["high_rate"], 3), round(1 - truth["underreport_high_safety"], 3),
                     abs(gap["high_rate"] - (1 - truth["underreport_high_safety"])) <= TOL["rate"]))
    safety = truth["latent_safety_by_team"]
    true_low = np.array([safety[str(int(t))] < truth["low_safety_cutoff"] for t in gap["team_id"]])
    share = float((true_low == gap["low_safety"]).mean())
    rows.append(_row("low_safety_teams_identified_from_survey", round(share, 3), 1.0, share >= 0.75))

    control_regions = {i for i, r in enumerate(REGIONS) if r[2] is None}
    region_of_team = dict(zip(dims["dim_team"]["team_id"], dims["dim_team"]["region_id"]))
    teams = [int(t) for t in ew["team_id"]]
    ctrl = [t for t in teams if region_of_team[t] in control_regions]
    div = [t for t in teams if region_of_team[t] not in control_regions]
    flag = dict(zip(teams, ew["flag_week"]))
    false_alarms = sum(1 for t in ctrl if flag[t] >= 0)
    rows.append(_row("control_teams_falsely_flagged", false_alarms, 0, false_alarms == 0))
    crossing = true_crossing_weeks(latent_team_week, fr)
    rise = {t: crossing[t] + truth["lag_weeks"] for t in div if crossing[t] >= 0}
    early = sum(1 for t in rise if 0 <= flag[t] <= rise[t]) / max(len(rise), 1)
    rows.append(_row("teams_flagged_before_true_hazard_rise", round(early, 3), 1.0, early >= 0.8,
                     "hazard starts rising lag_weeks after the planted crossing"))
    bias = [flag[t] - crossing[t] for t in div if flag[t] >= 0 and crossing[t] >= 0]
    med = float(np.median(bias)) if bias else float("nan")
    rows.append(_row("warning_week_minus_true_crossing_week", med, 0.0, bool(bias) and abs(med) <= TOL["bias_weeks"],
                     "negative means the flag came before the planted crossing"))

    tz_found = {int(a.split("_")[-1]) for s, a, v in cleaning if a.startswith("tz_offset_hours_cluster_") and v == 8}
    tz_true = {int(c) for c, r in zip(dims["dim_cluster"]["cluster_id"], dims["dim_cluster"]["region_id"]) if r == 2}
    rows.append(_row("timezone_clusters_found", len(tz_found), len(tz_true), tz_found == tz_true))
    dups = [v for s, a, v in cleaning if s == "telemetry" and a == "duplicates_removed"][0]
    planted_dups = ledger["telemetry.exact_duplicate"] + ledger["telemetry.restated_duplicate"]
    rows.append(_row("telemetry_duplicates_removed", dups, planted_dups, dups == planted_dups))
    return rows


def summarize(rows):
    hits = sum(r["verdict"] == "hit" for r in rows)
    return {"hits": hits, "total": len(rows), "misses": [r["metric"] for r in rows if r["verdict"] == "miss"]}

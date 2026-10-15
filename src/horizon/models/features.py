"""Observable features for the models. Nothing here reads the answer key."""

import numpy as np

BASELINE_WEEKS = 4


def capacity_index(tw, baseline_weeks=BASELINE_WEEKS):
    """Staffing relative to demand, 1.0 = where each team started.

    (headcount / starting headcount) / (CPU utilization / starting utilization).
    Utilization stands in for workload, since demand and AI load both raise it.
    """
    team, out = tw["team_id"], np.full(len(tw["team_id"]), np.nan)
    for t in np.unique(team):
        m = team == t
        hc, util = tw["headcount"][m], tw["mean_cpu_util_pct"][m]
        out[m] = (hc / hc[:baseline_weeks].mean()) / (util / util[:baseline_weeks].mean())
    return out


def wear_proxy(tw):
    """Cumulative AI budget share, a stand-in for deferred maintenance."""
    team, out = tw["team_id"], np.zeros(len(tw["team_id"]))
    for t in np.unique(team):
        m = team == t
        out[m] = np.cumsum(np.nan_to_num(tw["ai_share_known"][m])) / 13.0
    return out


def lag(x, weeks):
    """Shift a per-team series later by `weeks`, padding with its first value."""
    if weeks <= 0:
        return x.copy()
    return np.concatenate([np.full(weeks, x[0]), x[: len(x) - weeks]])

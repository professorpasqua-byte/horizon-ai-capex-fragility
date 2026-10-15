"""Model 3b: how many real outages never get a ticket, and who skips them?

Outages are detected from telemetry (failed health checks), which does not
depend on anyone filing anything. Each detected outage is matched to an
incident ticket on the same cluster within a time window. The filing rate is
then compared with the team's pulse-survey psychological safety score.
"""

import numpy as np

from horizon.gold.build import HOUR, START

SAFETY_MIDPOINT = 3.0  # midpoint of the 1 to 5 survey scale


def outage_episodes(gold_ch, hours, gap_hours=3):
    """(cluster_id, team_id, start_hour) for each run of failed health checks."""
    C = len(np.unique(gold_ch["cluster_id"]))
    health = gold_ch["health_ok"].reshape(C, hours)
    team = gold_ch["team_id"].reshape(C, hours)[:, 0]
    cl, tm, st = [], [], []
    for c in range(C):
        f = np.flatnonzero(health[c] == 0)
        if len(f):
            starts = f[np.r_[True, np.diff(f) > gap_hours]]
            cl += [c] * len(starts)
            tm += [int(team[c])] * len(starts)
            st += starts.tolist()
    return np.array(cl), np.array(tm), np.array(st)


def reporting_gap(gold_ch, tickets, tw, hours, window=(-12, 6)):
    cl, tm, st = outage_episodes(gold_ch, hours)
    inc = tickets["ticket_type"] == "incident"
    th = (tickets["created_utc"][inc] - START) // HOUR
    tc = tickets["cluster_id"][inc]
    matched = np.zeros(len(cl), dtype=bool)
    for c in np.unique(cl):
        hrs = np.sort(th[tc == c])
        e = np.flatnonzero(cl == c)
        lo = np.searchsorted(hrs, st[e] + window[0], "left")
        hi = np.searchsorted(hrs, st[e] + window[1], "right")
        matched[e] = hi > lo
    teams = np.unique(tw["team_id"])
    n = np.array([(tm == t).sum() for t in teams])
    k = np.array([matched[tm == t].sum() for t in teams])
    safety = np.array([np.nanmean(tw["safety_known"][tw["team_id"] == t]) for t in teams])
    rate = np.where(n > 0, k / np.maximum(n, 1), np.nan)
    low = safety < SAFETY_MIDPOINT
    n_lo, k_lo, n_hi, k_hi = n[low].sum(), k[low].sum(), n[~low].sum(), k[~low].sum()
    p_lo, p_hi = k_lo / max(n_lo, 1), k_hi / max(n_hi, 1)
    se = np.sqrt(p_lo * (1 - p_lo) / max(n_lo, 1) + p_hi * (1 - p_hi) / max(n_hi, 1))
    return {
        "team_id": teams, "episodes": n, "ticketed": k, "filing_rate": rate, "safety_score": safety,
        "low_safety": low, "low_rate": float(p_lo), "high_rate": float(p_hi),
        "rate_gap": float(p_hi - p_lo), "rate_gap_ci": (float(p_hi - p_lo - 1.96 * se), float(p_hi - p_lo + 1.96 * se)),
        "episodes_total": int(n.sum()), "unticketed_total": int(n.sum() - k.sum()),
        "incident_tickets_total": int(inc.sum()),
    }

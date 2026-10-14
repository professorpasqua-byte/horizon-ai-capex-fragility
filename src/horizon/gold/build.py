"""Gold: analysis-ready tables.

gold_cluster_hour  one row per cluster per hour (complete grid, gaps kept as NaN)
gold_team_week     one row per team per week (the grain the models use)

Slower sources are joined as-of the date each record was delivered, so a row
only holds what was known at that moment (no look-ahead).
"""

import numpy as np

from horizon.config import WINDOW_START

HOUR = np.timedelta64(1, "h")
DAY = np.timedelta64(1, "D")
START = np.datetime64(WINDOW_START.replace(tzinfo=None), "us")
HPW = 168
METRICS = ("cpu_util_pct", "inlet_temp_c", "throttle_pct", "packet_drop_pct", "p99_latency_ms")


def asof_join(q_group, q_time, e_group, e_time, e_order, e_vals):
    """For each query, take the event in its group delivered at or before q_time
    with the highest e_order (ties: latest delivered). NaN when nothing was known yet."""
    out = {k: np.full(len(q_group), np.nan) for k in e_vals}
    for g in np.unique(q_group):
        qi = np.flatnonzero(q_group == g)
        ei = np.flatnonzero(e_group == g)
        if len(ei) == 0:
            continue
        ei = ei[np.argsort(e_time[ei], kind="stable")]
        best, cur = np.empty(len(ei), dtype=int), 0
        for j in range(len(ei)):
            if e_order[ei[j]] >= e_order[ei[cur]]:
                cur = j
            best[j] = cur
        pos = np.searchsorted(e_time[ei], q_time[qi], side="right") - 1
        ok = pos >= 0
        src = ei[best[pos[ok]]]
        for k, v in e_vals.items():
            out[k][qi[ok]] = v[src]
    return out


def build_cluster_hour(silver, dims, hours):
    cl, tm, rg = dims["dim_cluster"], dims["dim_team"], dims["dim_region"]
    cid, c_team, c_region = (np.asarray(cl[k]) for k in ("cluster_id", "team_id", "region_id"))
    C, H, T, R = len(cid), hours, len(tm["team_id"]), len(rg["region_id"])
    t = silver["telemetry"]
    hour = (t["ts_utc"] - START) // HOUR
    ok = (hour >= 0) & (hour < H)
    key = t["cluster_id"][ok] * H + hour[ok]
    n = C * H
    count = np.bincount(key, minlength=n)
    out = {
        "cluster_id": np.repeat(cid, H), "region_id": np.repeat(c_region, H),
        "team_id": np.repeat(c_team, H), "hour_index": np.tile(np.arange(H), C),
        "ts_utc": np.tile(START + np.arange(H) * HOUR, C), "reading_count": count,
    }
    for m in METRICS:
        v = t[m][ok]
        good = ~np.isnan(v)
        s = np.bincount(key[good], weights=v[good], minlength=n)
        c = np.bincount(key[good], minlength=n)
        out[m] = np.where(c > 0, s / np.maximum(c, 1), np.nan)
    fail = np.bincount(key, weights=(1 - t["health_ok"][ok]).astype(float), minlength=n) > 0
    out["health_ok"] = np.where(count > 0, np.where(fail, 0.0, 1.0), np.nan)

    ends = START + (np.arange(H) + 1) * HOUR
    to_c = lambda d, groups, idx: d.reshape(groups, H)[idx].ravel()
    tq_g, tq_t = np.repeat(np.arange(T), H), np.tile(ends, T)
    s = silver["staffing"]
    st = asof_join(tq_g, tq_t, s["team_id"], s["delivered_at"], s["week_ending"].astype("int64"), {
        "headcount_known": s["headcount"].astype(float),
        "funded_known": s["funded_headcount"].astype(float),
        "overtime_known": s["overtime_hours_per_head"]})
    sv = silver["survey"]
    good = ~np.isnan(sv["safety_score"])
    su = asof_join(tq_g, tq_t, sv["team_id"][good], sv["delivered_at"][good],
                   sv["month_start"][good].astype("int64"), {"safety_known": sv["safety_score"][good]})
    b = silver["budget"]
    bu = asof_join(np.repeat(np.arange(R), H), np.tile(ends, R), b["region_id"], b["delivered_at"],
                   b["quarter_start"].astype("int64"), {"ai_share_known": b["ai_share"], "core_share_known": b["core_share"]})
    for k, v in {**st, **su}.items():
        out[k] = to_c(v, T, c_team)
    for k, v in bu.items():
        out[k] = to_c(v, R, c_region)
    per_team = np.bincount(c_team, minlength=T)
    out["heads_per_cluster_known"] = out["headcount_known"] / per_team[out["team_id"]]
    return out


def _nanmean_team(a, ct, T):
    """a: (clusters, weeks, hours) -> team-week mean over valid readings."""
    s, c = np.nan_to_num(a).sum(axis=2), (~np.isnan(a)).sum(axis=2)
    out = np.full((T, a.shape[1]), np.nan)
    for t in range(T):
        m = ct == t
        cs = c[m].sum(0)
        out[t] = np.where(cs > 0, s[m].sum(0) / np.maximum(cs, 1), np.nan)
    return out


def build_team_week(silver, gold_ch, dims, hours):
    tm, cl = dims["dim_team"], dims["dim_cluster"]
    T, C, H = len(tm["team_id"]), len(cl["cluster_id"]), hours
    W = H // HPW
    ct, region_of_team = np.asarray(cl["team_id"]), np.asarray(tm["region_id"])
    wk = np.arange(W)
    week_end = START + (wk + 1) * 7 * DAY
    grid = lambda: np.full((T, W), np.nan)

    s = silver["staffing"]
    cur = s["is_current"]
    widx = ((s["week_ending"][cur] - np.timedelta64(6, "D")) - START.astype("datetime64[D]")) // (7 * DAY)
    inr = (widx >= 0) & (widx < W)
    out_g = {}
    for name, col in (("headcount", "headcount"), ("funded_headcount", "funded_headcount"),
                      ("hires", "hires"), ("departures", "departures"), ("reductions", "reductions"),
                      ("overtime_hours_per_head", "overtime_hours_per_head")):
        g = grid()
        g[s["team_id"][cur][inr], widx[inr]] = s[col][cur][inr].astype(float)
        out_g[name] = g
    staffing_missing = np.isnan(out_g["headcount"])
    for name in ("headcount", "funded_headcount", "overtime_hours_per_head"):
        for t in range(T):
            v = out_g[name][t]
            if np.isnan(v).any() and (~np.isnan(v)).any():
                out_g[name][t] = np.interp(wk, wk[~np.isnan(v)], v[~np.isnan(v)])

    tk = silver["tickets"]
    cw = (tk["created_utc"] - START) // (7 * DAY)
    inr = (cw >= 0) & (cw < W)
    key = tk["team_id"] * W + cw
    inc = tk["ticket_type"] == "incident"
    out_g["incident_tickets"] = np.bincount(key[inr & inc], minlength=T * W).reshape(T, W).astype(float)
    out_g["routine_tickets"] = np.bincount(key[inr & ~inc], minlength=T * W).reshape(T, W).astype(float)
    rr = ~inc & ~np.isnat(tk["resolved_utc"]) & inr
    hrs, k = (tk["resolved_utc"][rr] - tk["created_utc"][rr]) / HOUR, key[rr]
    med = grid()
    for g_ in np.unique(k):
        med[g_ // W, g_ % W] = np.median(hrs[k == g_])
    out_g["median_resolution_hours"] = med
    backlog = grid()
    for t in range(T):
        m = (tk["team_id"] == t) & ~inc
        created = np.sort(tk["created_utc"][m])
        resolved = np.sort(tk["resolved_utc"][m][~np.isnat(tk["resolved_utc"][m])])
        backlog[t] = np.searchsorted(created, week_end, "left") - np.searchsorted(resolved, week_end, "left")
    out_g["open_backlog_end"] = backlog

    fields = lambda name: gold_ch[name].reshape(C, H)[:, : W * HPW].reshape(C, W, HPW)
    for m in ("cpu_util_pct", "throttle_pct", "packet_drop_pct", "p99_latency_ms"):
        out_g[f"mean_{m}"] = _nanmean_team(fields(m), ct, T)
    h = fields("health_ok")
    n_clusters = np.bincount(ct, minlength=T)
    fail_hours, coverage = grid(), grid()
    for t in range(T):
        m = ct == t
        fail_hours[t] = (h[m] == 0).sum(axis=(0, 2))
        coverage[t] = (~np.isnan(h[m])).sum(axis=(0, 2)) / (n_clusters[t] * HPW)
    out_g["health_fail_hours"], out_g["telemetry_coverage"] = fail_hours, coverage
    episodes = np.zeros((T, W))
    hh = gold_ch["health_ok"].reshape(C, H)
    for c in range(C):
        f = np.flatnonzero(hh[c] == 0)
        if len(f):
            starts = f[np.r_[True, np.diff(f) > 3]] // HPW
            np.add.at(episodes[ct[c]], starts[starts < W], 1)
    out_g["detected_outage_episodes"] = episodes

    tq_g, tq_t = np.repeat(np.arange(T), W), np.tile(week_end, T)
    sv = silver["survey"]
    good = ~np.isnan(sv["safety_score"])
    su = asof_join(tq_g, tq_t, sv["team_id"][good], sv["delivered_at"][good],
                   sv["month_start"][good].astype("int64"), {"safety_known": sv["safety_score"][good]})
    out_g["safety_known"] = su["safety_known"].reshape(T, W)
    R = len(dims["dim_region"]["region_id"])
    b = silver["budget"]
    bu = asof_join(np.repeat(np.arange(R), W), np.tile(week_end, R), b["region_id"], b["delivered_at"],
                   b["quarter_start"].astype("int64"), {"ai_share_known": b["ai_share"], "core_share_known": b["core_share"]})
    for k_, v in bu.items():
        out_g[k_] = v.reshape(R, W)[region_of_team]

    out = {"team_id": np.repeat(np.arange(T), W), "region_id": np.repeat(region_of_team, W),
           "week_index": np.tile(wk, T), "week_start": np.tile(START + wk * 7 * DAY, T),
           "staffing_missing": staffing_missing.ravel()}
    out.update({k_: v.ravel() for k_, v in out_g.items()})
    return out


def build_gold(silver, dims, hours=None):
    if hours is None:
        hours = int((silver["telemetry"]["ts_utc"].max() - START) // HOUR) + 1
    ch = build_cluster_hour(silver, dims, hours)
    return {"gold_cluster_hour": ch, "gold_team_week": build_team_week(silver, ch, dims, hours)}

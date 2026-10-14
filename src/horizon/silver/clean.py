"""Silver: clean every source. Fix what is fixable, flag the rest.

Slow sources keep every delivered version (is_current marks the latest) so the
gold layer can join on what was known at the time.
"""

import re

import numpy as np

HOUR = np.timedelta64(1, "h")


def norm(label) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(label).strip().lower()).strip("-")


def keep_latest(keys, order):
    """Indices of the last row (by order) within each key group."""
    keys = [np.asarray(k).astype("int64") for k in keys]
    srt = np.lexsort([np.asarray(order).astype("int64"), *keys[::-1]])
    last = np.ones(len(srt), dtype=bool)
    last[:-1] = np.any([k[srt][1:] != k[srt][:-1] for k in keys], axis=0)
    return srt[last]


def _ids(labels, names, ids, dq, source):
    table = {norm(n): int(i) for n, i in zip(names, ids)}
    out = np.array([table.get(norm(x), -1) for x in labels])
    dq.append((source, "unmapped_labels", int((out < 0).sum())))
    return out


def _parse_ts(strings):
    base = np.array([x[:19] if x else "NaT" for x in strings], dtype="datetime64[s]")
    off = np.array([0 if (not x or x.endswith("Z")) else int(x[19:22]) for x in strings])
    return base.astype("datetime64[us]") - off.astype("int64").astype("timedelta64[h]")


def clean_telemetry(t, dq):
    diff = (t["ts_reported"] - t["ingested_ts"]) / HOUR
    clusters = np.unique(t["cluster_id"])
    med = {c: float(np.median(diff[t["cluster_id"] == c])) for c in clusters}
    base = float(np.median(list(med.values())))
    offset = np.zeros(int(clusters.max()) + 1)
    for c in clusters:
        offset[c] = round(med[c] - base)
        if offset[c] != 0:
            dq.append(("telemetry", f"tz_offset_hours_cluster_{int(c)}", int(offset[c])))
    ts = t["ts_reported"] - offset[t["cluster_id"]].astype("int64").astype("timedelta64[h]")

    temp = t["inlet_temp_c"].copy()
    sentinel = temp == -999
    temp[sentinel] = np.nan
    dq.append(("telemetry", "sentinels_nulled", int(sentinel.sum())))
    lag = t["ingested_ts"] - ts
    dq.append(("telemetry", "late_arrivals", int((lag > np.median(lag) + HOUR).sum())))

    keep = keep_latest([t["cluster_id"], ts], t["ingested_ts"])
    dq.append(("telemetry", "duplicates_removed", len(ts) - len(keep)))
    out = {k: t[k][keep] for k in (
        "cluster_id", "cpu_util_pct", "throttle_pct", "packet_drop_pct", "p99_latency_ms",
        "health_check_ok", "ingested_ts")}
    out["ts_utc"], out["inlet_temp_c"] = ts[keep], temp[keep]
    out["health_ok"] = out.pop("health_check_ok")
    return out


def clean_staffing(s, dims, dq):
    team = _ids(s["team_label"], dims["dim_team"]["team_name"], dims["dim_team"]["team_id"], dq, "staffing")
    ot = s["overtime_hours_per_head"].copy()
    bad = ot < 0
    ot[bad] = np.nan
    dq.append(("staffing", "sentinels_nulled", int(bad.sum())))
    cur = np.zeros(len(team), dtype=bool)
    cur[keep_latest([team, s["week_ending"]], s["delivered_at"])] = True
    dq.append(("staffing", "superseded_versions", int((~cur).sum())))
    out = {k: s[k] for k in ("week_ending", "funded_headcount", "headcount", "hires",
                             "departures", "reductions", "delivered_at")}
    return dict(out, team_id=team, overtime_hours_per_head=ot, is_current=cur)


def clean_budget(b, dims, dq):
    rid = _ids(b["region_name"], dims["dim_region"]["region_name"], dims["dim_region"]["region_id"], dq, "budget")
    money = lambda c: np.array([float(x.strip().lstrip("$").rstrip("M")) for x in b[c]])
    total, core = money("total_budget"), money("core_budget")
    cur = np.zeros(len(rid), dtype=bool)
    cur[keep_latest([rid, b["quarter_start"]], b["delivered_at"])] = True
    return {
        "region_id": rid, "quarter_start": b["quarter_start"], "version": b["version"],
        "total_budget_musd": total, "ai_budget_musd": money("ai_budget"), "core_budget_musd": core,
        "ai_share": np.array([float(x.rstrip("%")) / 100 for x in b["ai_share"]]),
        "core_share": core / total, "delivered_at": b["delivered_at"], "is_current": cur,
    }


def clean_tickets(tk, dq):
    keep = np.sort(keep_latest([tk["ticket_id"]], tk["delivered_at"]))
    dq.append(("tickets", "duplicates_removed", len(tk["ticket_id"]) - len(keep)))
    t = {k: v[keep] for k, v in tk.items() if not k.startswith("_")}
    blank = np.isnan(t["severity"])
    dq.append(("tickets", "blank_severity_filled", int(blank.sum())))
    return {
        "ticket_id": t["ticket_id"], "created_utc": _parse_ts(t["created_ts"]),
        "resolved_utc": _parse_ts(t["resolved_ts"]), "team_id": t["team_id"],
        "cluster_id": t["cluster_id"], "ticket_type": t["ticket_type"],
        "severity": np.where(blank, 1.0, t["severity"]), "severity_was_blank": blank,
        "delivered_at": t["delivered_at"],
    }


def clean_postmortems(pm, dq):
    cause = np.array(["hardware" if ("hard" in x.lower() or "hw" in x.lower()) else "process" for x in pm["root_cause"]])
    dq.append(("postmortems", "causes_normalized", len(cause)))
    return {"ticket_id": pm["ticket_id"], "written_ts": pm["written_ts"], "root_cause": cause,
            "delivered_at": pm["delivered_at"]}


def clean_survey(sv, dims, dq):
    team = _ids(sv["team_label"], dims["dim_team"]["team_name"], dims["dim_team"]["team_id"], dq, "survey")
    return {"team_id": team, "month_start": sv["month_start"], "invited": sv["invited"],
            "responses": sv["responses"], "safety_score": sv["mean_safety_score"],
            "delivered_at": sv["delivered_at"]}


def clean_all(bronze, dims):
    dq = []
    silver = {
        "telemetry": clean_telemetry(bronze["telemetry"], dq),
        "staffing": clean_staffing(bronze["staffing"], dims, dq),
        "budget": clean_budget(bronze["budget"], dims, dq),
        "tickets": clean_tickets(bronze["tickets"], dq),
        "postmortems": clean_postmortems(bronze["postmortems"], dq),
        "survey": clean_survey(bronze["survey"], dims, dq),
    }
    return silver, dq

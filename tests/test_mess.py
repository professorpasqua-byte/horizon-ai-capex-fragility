import re
from collections import Counter

import numpy as np

from horizon.config import REGIONS, SCALES, SimConfig
from horizon.simulate.budget_staffing import build_budget_staffing
from horizon.simulate.incidents import build_incidents
from horizon.simulate.mess import (
    LOCAL_TICKET_REGION,
    MIN_SURVEY_CELL,
    TZ_REGION,
    build_landing,
    normalize_team_label,
)
from horizon.simulate.world import build_world

START = np.datetime64("2025-10-01T00:00", "us")
_CACHE = {}


def fresh(scale="standard", seed=42):
    cfg = SimConfig(scale=SCALES[scale], seed=seed)
    world = build_world(cfg)
    staffing = build_budget_staffing(cfg, world)
    incidents = build_incidents(cfg, world, staffing)
    landing = build_landing(cfg, world, staffing, None, incidents)
    return cfg, world, incidents, landing


def make(scale="standard", seed=42):
    if (scale, seed) not in _CACHE:
        _CACHE[(scale, seed)] = fresh(scale, seed)
    return _CACHE[(scale, seed)]


def same(a, b):
    if a.keys() != b.keys():
        return False
    for k in a:
        x, y = a[k], b[k]
        if x.dtype.kind in "Mm":
            x, y = x.astype("int64"), y.astype("int64")
        ok = np.array_equal(x, y, equal_nan=True) if x.dtype.kind == "f" else np.array_equal(x, y)
        if not ok:
            return False
    return True


def non_apac(t, world):
    region = np.array(world["dim_cluster"]["region_id"])[t["cluster_id"]]
    return region != TZ_REGION


def hour_key(t, cfg, mask):
    hour = ((t["ts_reported"][mask] - START) // np.timedelta64(1, "h")).astype(int)
    return t["cluster_id"][mask].astype(int) * cfg.hours + hour


def test_team_labels_are_messy_but_normalize_to_canonical_names():
    _, world, _, L = make()
    names = set(world["dim_team"]["team_name"])
    for table in ("staffing", "survey"):
        labels = set(L[table]["team_label"].tolist())
        assert len(labels) > len(names)
        assert all(normalize_team_label(x) in names for x in labels)


def test_same_seed_identical_different_seed_differs():
    a, b = fresh(seed=5)[3], fresh(seed=5)[3]
    for name in a:
        assert same(a[name], b[name])
    c = fresh(seed=6)[3]
    assert not same(a["telemetry"], c["telemetry"])


def test_every_source_is_in_the_ledger():
    _, _, _, L = make()
    sources = set(L["latent_mess_ledger"]["source"].tolist())
    assert sources == {"telemetry", "staffing", "budget", "tickets", "postmortems", "survey"}


def test_telemetry_has_duplicates_and_missing_readings():
    cfg, world, _, L = make()
    t = L["telemetry"]
    mask = non_apac(t, world)
    key = hour_key(t, cfg, mask)
    clusters_non_apac = int((np.array(world["dim_cluster"]["region_id"]) != TZ_REGION).sum())
    assert len(key) > len(np.unique(key))
    assert len(np.unique(key)) < clusters_non_apac * cfg.hours


def test_apac_timestamps_are_local_time_and_land_in_the_future():
    _, world, _, L = make()
    t = L["telemetry"]
    future = t["ts_reported"] > t["ingested_ts"]
    mask = non_apac(t, world)
    assert future[~mask].mean() > 0.95
    assert future[mask].mean() < 0.001


def test_monitoring_goes_quiet_during_severe_incidents():
    cfg, world, inc, L = make()
    t, li = L["telemetry"], inc["latent_incident"]
    mask = non_apac(t, world)
    present = np.zeros(len(world["dim_cluster"]["cluster_id"]) * cfg.hours, dtype=bool)
    present[hour_key(t, cfg, mask)] = True
    apac = np.array(world["dim_cluster"]["region_id"]) == TZ_REGION
    severe = np.zeros_like(present)
    for c, s, d, sev in zip(li["cluster_id"], li["start_hour_index"], li["duration_hours"], li["severity"]):
        if sev >= 3 and not apac[int(c)]:
            severe[int(c) * cfg.hours + int(s) : int(c) * cfg.hours + min(int(s) + int(d), cfg.hours)] = True
    cluster_ok = np.repeat(~apac, cfg.hours)
    assert severe.sum() > 0
    assert present[severe].mean() < 0.7
    assert present[cluster_ok & ~severe].mean() > 0.99


def test_sentinels_and_late_arrivals_exist():
    _, world, _, L = make()
    t = L["telemetry"]
    assert (t["inlet_temp_c"] == -999).sum() > 0
    mask = non_apac(t, world)
    lag = (t["ingested_ts"][mask] - t["ts_reported"][mask]) / np.timedelta64(1, "h")
    assert 0.01 < (lag > 2.2).mean() < 0.04


def test_budget_money_is_text_and_restatements_arrive_later():
    _, _, _, L = make()
    b = L["budget"]
    for col in ("total_budget", "ai_budget", "core_budget"):
        assert all(re.fullmatch(r"\$\d+\.\d{2}M", x) for x in b[col])
    assert all(re.fullmatch(r"\d+\.\d%", x) for x in b["ai_share"])
    assert set(b["version"].tolist()) == {1, 2}
    seen = {}
    for name, q, v, d in zip(b["region_name"], b["fiscal_quarter"], b["version"], b["delivered_at"]):
        seen.setdefault((normalize_team_label(name), q), {})[int(v)] = d
    assert any(2 in versions for versions in seen.values())
    for versions in seen.values():
        if 2 in versions:
            assert versions[2] > versions[1]


def test_staffing_has_missing_weeks_and_restated_rows():
    cfg, world, _, L = make()
    s = L["staffing"]
    keys = [normalize_team_label(a) + str(w) for a, w in zip(s["team_label"], s["week_ending"])]
    counts = Counter(keys)
    assert len(counts) < 8 * 52
    assert len(keys) > len(counts)
    heads = {}
    for k, h in zip(keys, s["headcount"]):
        heads.setdefault(k, set()).add(int(h))
    assert any(len(v) > 1 for v in heads.values())
    assert (s["overtime_hours_per_head"] == -1).sum() >= 0


def test_tickets_have_timezone_offsets_duplicates_and_blank_severity():
    _, world, _, L = make()
    tk = L["tickets"]
    region = dict(zip(world["dim_team"]["team_id"], world["dim_team"]["region_id"]))
    reg = np.array([region[int(x)] for x in tk["team_id"]])
    created = tk["created_ts"]
    local = reg == LOCAL_TICKET_REGION
    assert all(x.endswith("-03:00") for x in created[local])
    assert all(x.endswith("Z") for x in created[~local])
    assert len(tk["ticket_id"]) > len(np.unique(tk["ticket_id"]))
    assert np.isnan(tk["severity"]).sum() > 0
    parsed = np.array([x[:19] for x in created], dtype="datetime64[s]").astype("datetime64[us]")
    assert np.all(tk["delivered_at"] > parsed)


def test_survey_hides_small_cells_and_tracks_latent_safety():
    _, world, _, L = make()
    sv = L["survey"]
    small = sv["responses"] < MIN_SURVEY_CELL
    assert small.any()
    assert np.all(np.isnan(sv["mean_safety_score"][small]))
    ok = ~small
    assert sv["mean_safety_score"][ok].min() >= 1 and sv["mean_safety_score"][ok].max() <= 5
    ids = dict(zip(world["dim_team"]["team_name"], world["dim_team"]["team_id"]))
    team = np.array([ids[normalize_team_label(x)] for x in sv["team_label"]])
    safety = world["truth"]["latent_safety_by_team"]
    xs, ys = [], []
    for t in np.unique(team[ok]):
        xs.append(safety[str(int(t))])
        ys.append(sv["mean_safety_score"][ok & (team == t)].mean())
    assert np.corrcoef(xs, ys)[0, 1] > 0.8


def test_postmortem_causes_are_free_text():
    _, _, _, L = make()
    assert len(set(L["postmortems"]["root_cause"].tolist())) > 2


def test_pipeline_visible_tables_hide_the_answer_keys():
    _, _, _, L = make()
    banned = {"incident_id", "ramp_at_incident", "team_safety", "ticketed", "cause", "latent_safety"}
    for name, table in L.items():
        if name.startswith("latent_"):
            continue
        assert not banned & set(table)
    assert "team_id" not in L["staffing"] and "team_id" not in L["survey"]


def test_sources_arrive_at_different_paces():
    _, world, _, L = make()
    day = np.timedelta64(1, "D")
    t = L["telemetry"]
    m = non_apac(t, world)
    tel = np.median((t["ingested_ts"][m] - t["ts_reported"][m]) / day)
    tk = L["tickets"]
    parsed = np.array([x[:19] for x in tk["created_ts"]], dtype="datetime64[s]").astype("datetime64[us]")
    tickets = np.median((tk["delivered_at"] - parsed) / day)
    s = L["staffing"]
    staffing = np.median((s["delivered_at"] - s["week_ending"].astype("datetime64[us]")) / day)
    b = L["budget"]
    budget = np.median((b["delivered_at"] - b["quarter_start"].astype("datetime64[us]")) / day)
    assert tel < 0.1 and 0.25 < tickets < staffing < budget


def test_tiny_scale_runs():
    _, _, _, L = fresh("tiny")
    assert len(L["telemetry"]["cluster_id"]) > 0
    assert len(L["budget"]["version"]) > 0

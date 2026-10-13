import numpy as np

from horizon.config import REGIONS, SCALES, HiddenTruth, SimConfig
from horizon.simulate.budget_staffing import build_budget_staffing
from horizon.simulate.incidents import (
    build_incidents,
    incident_rate,
    lag_series,
    overlay_incidents,
    ramp,
)
from horizon.simulate.telemetry import build_telemetry
from horizon.simulate.world import build_world

CONTROL = [i for i, r in enumerate(REGIONS) if r[2] is None][0]
TRUTH = HiddenTruth()


def make(scale="standard", seed=42):
    cfg = SimConfig(scale=SCALES[scale], seed=seed)
    world = build_world(cfg)
    staffing = build_budget_staffing(cfg, world)
    return cfg, world, build_incidents(cfg, world, staffing)


def same(a, b):
    if a.keys() != b.keys():
        return False
    for k in a:
        x, y = a[k], b[k]
        if x.dtype.kind == "M":
            x, y = x.astype("int64"), y.astype("int64")
        if not np.array_equal(x, y):
            return False
    return True


def test_ramp_is_a_hinge_at_the_fracture_ratio():
    assert ramp(0.80, TRUTH) == 0
    assert ramp(0.72, TRUTH) == 0
    assert abs(ramp(0.67, TRUTH) - 0.5) < 1e-9
    assert abs(ramp(0.62, TRUTH) - 1) < 1e-9
    assert ramp(0.30, TRUTH) == 1


def test_lag_series_shifts_later_and_pads_with_first_value():
    x = np.array([[9, 8, 7, 6, 5, 4]])
    assert lag_series(x, 2).tolist() == [[9, 9, 9, 8, 7, 6]]
    assert lag_series(x, 0).tolist() == x.tolist()
    assert lag_series(x, 10).tolist() == [[9, 9, 9, 9, 9, 9]]


def test_hazard_responds_to_ratio_from_lag_weeks_earlier():
    ratio = np.ones((1, 20))
    ratio[0, 10:] = 0.5  # drops at week 10
    rate, _ = incident_rate(ratio, np.zeros((1, 20)), TRUTH)
    assert np.all(rate[0, : 10 + TRUTH.lag_weeks] == rate[0, 0])
    assert rate[0, 10 + TRUTH.lag_weeks] > 3 * rate[0, 0]


def test_same_seed_identical_different_seed_differs():
    a, b = make(seed=5)[2], make(seed=5)[2]
    assert same(a["latent_incident"], b["latent_incident"])
    assert same(a["fact_ticket"], b["fact_ticket"])
    c = make(seed=6)[2]
    assert len(a["latent_incident"]["incident_id"]) != len(c["latent_incident"]["incident_id"]) or not same(
        a["latent_incident"], c["latent_incident"]
    )


def test_strained_region_has_far_higher_incident_rate_than_control_after_the_lag():
    _, _, t = make()
    inc = t["latent_incident"]
    late = inc["week_index"] >= 33
    na = ((inc["region_id"] == 0) & late).sum()
    ctrl = ((inc["region_id"] == CONTROL) & late).sum()
    assert na > 2 * ctrl


def test_incidents_under_strain_are_more_severe():
    _, _, t = make()
    inc = t["latent_incident"]
    calm = inc["severity"][inc["ramp_at_incident"] == 0].mean()
    strained = inc["severity"][inc["ramp_at_incident"] > 0.5].mean()
    assert strained > calm


def test_low_safety_teams_file_fewer_tickets():
    cfg, _, t = make()
    inc = t["latent_incident"]
    low = inc["team_safety"] < cfg.truth.low_safety_cutoff
    assert inc["ticketed"][~low].mean() - inc["ticketed"][low].mean() > 0.15


def test_ticket_links_are_consistent():
    _, _, t = make()
    inc, tk = t["latent_incident"], t["fact_ticket"]
    filed = inc["ticketed"] == 1
    assert np.all(inc["ticket_id"][filed] > 0)
    assert np.all(inc["ticket_id"][~filed] == -1)
    ids = tk["ticket_id"]
    assert len(np.unique(ids)) == len(ids)
    lookup = {int(i): k for k, i in enumerate(ids)}
    for iid in inc["ticket_id"][filed]:
        assert tk["ticket_type"][lookup[int(iid)]] == "incident"
    assert int((tk["ticket_type"] == "incident").sum()) == int(filed.sum())


def test_tickets_are_time_ordered_and_follow_the_incident():
    _, _, t = make()
    inc, tk = t["latent_incident"], t["fact_ticket"]
    assert np.all(np.diff(tk["created_ts"].astype("int64")) >= 0)
    lookup = {int(i): k for k, i in enumerate(tk["ticket_id"])}
    start = np.datetime64("2025-10-01T00:00:00", "us")
    for k in np.flatnonzero(inc["ticketed"] == 1)[:50]:
        row = lookup[int(inc["ticket_id"][k])]
        begin = start + np.timedelta64(int(inc["start_hour_index"][k]), "h")
        assert tk["created_ts"][row] >= begin


def test_postmortems_only_for_filed_severe_incidents():
    _, _, t = make()
    inc, tk, pm = t["latent_incident"], t["fact_ticket"], t["fact_postmortem"]
    filed_severe = set(inc["ticket_id"][(inc["ticketed"] == 1) & (inc["severity"] >= 3)].tolist())
    assert len(pm["ticket_id"]) > 0
    assert set(pm["ticket_id"].tolist()) <= filed_severe


def test_answer_key_columns_stay_out_of_observed_tables():
    _, _, t = make()
    banned = {"ramp_at_incident", "team_safety", "ticketed", "incident_id", "cause", "duration_hours"}
    for name in ("fact_ticket", "fact_postmortem"):
        assert not banned & set(t[name])
    assert "ramp_at_incident" in t["latent_incident"]


def test_routine_tickets_resolve_slower_in_strained_region_late_in_year():
    cfg, _, t = make()
    tk = t["fact_ticket"]
    routine = tk["ticket_type"] == "routine"
    done = ~np.isnat(tk["resolved_ts"])
    hours = (tk["resolved_ts"] - tk["created_ts"]).astype("timedelta64[m]").astype(float) / 60
    start = np.datetime64("2025-10-01T00:00:00", "us")
    region_of_team = {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3}
    reg = np.array([region_of_team[int(x)] for x in tk["team_id"]])
    early_cut = start + np.timedelta64(30, "D")
    first_month = tk["created_ts"] < early_cut
    late_q = tk["created_ts"] >= start + np.timedelta64(cfg.scale.days * 3 // 4, "D")
    base = hours[routine & done & first_month & (reg == 0)].mean()
    stressed = hours[routine & done & late_q & (reg == 0)].mean()
    control = hours[routine & done & late_q & (reg == CONTROL)].mean()
    assert stressed > 1.5 * control
    assert stressed > 1.5 * base


def test_overlay_marks_outages_and_spikes_latency_only_where_incidents_are():
    cfg, world, t = make()
    tel = build_telemetry(cfg, world)["fact_cluster_hour"]
    out = overlay_incidents(tel, t["latent_incident"], cfg)
    inc = t["latent_incident"]
    H = cfg.hours
    bad_hours = set()
    for c, s, d, sev in zip(inc["cluster_id"], inc["start_hour_index"], inc["duration_hours"], inc["severity"]):
        if sev >= 2:
            bad_hours.update(range(int(c) * H + int(s), int(c) * H + min(int(s) + int(d), H)))
    failed = set(np.flatnonzero(out["health_check_ok"] == 0).tolist())
    assert failed == bad_hours and len(failed) > 0
    assert out["p99_latency_ms"].mean() > tel["p99_latency_ms"].mean()
    assert "health_check_ok" not in tel  # the input was not modified


def test_tiny_scale_runs():
    cfg, _, t = make("tiny")
    assert len(t["fact_ticket"]["ticket_id"]) > 0
    assert "latent_incident" in t

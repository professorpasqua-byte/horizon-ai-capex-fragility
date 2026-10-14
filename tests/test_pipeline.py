import numpy as np

from horizon.bronze.ingest import to_bronze
from horizon.gold.build import HOUR, START, asof_join
from horizon.pipeline import run_pipeline
from horizon.simulate.budget_staffing import build_budget_staffing
from horizon.simulate.telemetry import build_telemetry
from test_mess import make as make_landing

_CACHE = {}


def run(scale="standard"):
    if scale not in _CACHE:
        cfg, world, inc, L = make_landing(scale)
        dims = {k: world[k] for k in ("dim_region", "dim_team", "dim_cluster")}
        _CACHE[scale] = (cfg, world, inc, L, dims, run_pipeline(L, dims))
    return _CACHE[scale]


def ledger(L):
    led = L["latent_mess_ledger"]
    return {f"{s}.{d}": int(r) for s, d, r in zip(led["source"], led["defect"], led["rows"])}


def dq_value(dq, source, action):
    return [v for s, a, v in dq if s == source and a == action][0]


def test_bronze_refuses_answer_key_tables_and_keeps_every_row():
    try:
        to_bronze({"latent_incident": {"a": np.arange(3)}})
        raise AssertionError("should have refused")
    except ValueError:
        pass
    _, _, _, L, _, (bronze, *_rest) = run()
    for name, t in bronze.items():
        assert len(t["_row_id"]) == len(L[name][next(k for k in L[name])])
        assert {"_row_id", "_source", "_batch_id"} <= set(t)


def test_silver_finds_and_fixes_the_timezone_error():
    cfg, world, _, L, dims, (_, silver, _, dq, _) = run()
    shifted = {int(a.split("_")[-1]): v for s, a, v in dq if a.startswith("tz_offset_hours_cluster_")}
    apac = {int(c) for c, r in zip(world["dim_cluster"]["cluster_id"], world["dim_cluster"]["region_id"]) if r == 2}
    assert set(shifted) == apac and set(shifted.values()) == {8}
    t = silver["telemetry"]
    assert (t["ts_utc"] <= t["ingested_ts"]).mean() > 0.999


def test_silver_cleaning_counts_match_the_ledger():
    _, _, _, L, _, (_, _, _, dq, _) = run()
    led = ledger(L)
    assert dq_value(dq, "telemetry", "duplicates_removed") == led["telemetry.exact_duplicate"] + led["telemetry.restated_duplicate"]
    assert dq_value(dq, "tickets", "duplicates_removed") == led["tickets.exact_duplicate"]
    assert dq_value(dq, "staffing", "superseded_versions") == led["staffing.restated_row"]
    assert dq_value(dq, "telemetry", "sentinels_nulled") >= led["telemetry.sentinel_value"]
    assert dq_value(dq, "staffing", "sentinels_nulled") >= led["staffing.sentinel_value"]
    assert dq_value(dq, "tickets", "blank_severity_filled") >= led["tickets.blank_severity"]
    for src in ("staffing", "budget", "survey"):
        assert dq_value(dq, src, "unmapped_labels") == 0


def test_silver_telemetry_matches_the_clean_world():
    cfg, world, _, L, _, (_, silver, _, _, _) = run()
    led = ledger(L)
    t = silver["telemetry"]
    assert len(t["cluster_id"]) == cfg.expected_gold_rows - led["telemetry.monitoring_gap"] - led["telemetry.random_missing"]
    clean = build_telemetry(cfg, world)["fact_cluster_hour"]
    hour = (t["ts_utc"] - START) // HOUR
    idx = t["cluster_id"] * cfg.hours + hour
    assert np.array_equal(clean["hour_index"][idx], hour)
    assert (clean["cpu_util_pct"][idx] != t["cpu_util_pct"]).sum() <= led["telemetry.restated_duplicate"]


def test_silver_tickets_recover_utc_times_exactly():
    _, _, inc, _, _, (_, silver, _, _, _) = run()
    tk, clean = silver["tickets"], inc["fact_ticket"]
    o = np.argsort(tk["ticket_id"])
    assert np.array_equal(tk["ticket_id"][o], clean["ticket_id"])
    assert np.array_equal(tk["created_utc"][o].astype("int64"), clean["created_ts"].astype("int64"))
    assert np.array_equal(np.isnat(tk["resolved_utc"][o]), np.isnat(clean["resolved_ts"]))
    done = ~np.isnat(clean["resolved_ts"])
    secs = lambda a: a.astype("datetime64[s]").astype("int64")  # the export keeps whole seconds
    assert np.array_equal(secs(tk["resolved_utc"][o][done]), secs(clean["resolved_ts"][done]))


def test_silver_budget_and_postmortems_match_the_truth():
    cfg, world, inc, _, _, (_, silver, _, _, _) = run()
    clean = build_budget_staffing(cfg, world)["fact_budget_quarterly"]
    want = {(int(r), np.datetime64(q, "D")): c for r, q, c in zip(clean["region_id"], clean["quarter_start"], clean["core_budget_musd"])}
    b = silver["budget"]
    for r, q, v, c in zip(b["region_id"], b["quarter_start"], b["version"], b["core_budget_musd"]):
        if v == 1:
            assert abs(want[(int(r), q)] - c) < 0.006
    li, pm = inc["latent_incident"], silver["postmortems"]
    cause = dict(zip(li["ticket_id"], li["cause"]))
    assert all(cause[int(t)] == c for t, c in zip(pm["ticket_id"], pm["root_cause"]))


def test_asof_join_never_looks_ahead_and_prefers_the_newer_week():
    g = np.zeros(2, dtype=int)
    out = asof_join(np.zeros(5, dtype=int), np.array([4, 5, 9, 10, 11]), g, np.array([5, 10]), np.array([1, 2]), {"v": np.array([10.0, 20.0])})
    assert np.isnan(out["v"][0]) and out["v"][1:].tolist() == [10.0, 10.0, 20.0, 20.0]
    late_old = asof_join(np.array([0]), np.array([11]), g, np.array([5, 10]), np.array([2, 1]), {"v": np.array([10.0, 20.0])})
    assert late_old["v"][0] == 10.0
    other = asof_join(np.array([7]), np.array([11]), g, np.array([5, 10]), np.array([1, 2]), {"v": np.array([10.0, 20.0])})
    assert np.isnan(other["v"][0])


def test_gold_headcount_known_matches_a_brute_force_as_of_lookup():
    cfg, world, _, _, dims, (_, silver, gold, _, _) = run()
    ch, s = gold["gold_cluster_hour"], silver["staffing"]
    rng = np.random.default_rng(0)
    for _ in range(150):
        team, hour = int(rng.integers(0, 8)), int(rng.integers(0, cfg.hours))
        cluster = [c for c, t in zip(world["dim_cluster"]["cluster_id"], world["dim_cluster"]["team_id"]) if t == team][0]
        end = START + (hour + 1) * HOUR
        seen = np.flatnonzero((s["team_id"] == team) & (s["delivered_at"] <= end))
        got = ch["headcount_known"][cluster * cfg.hours + hour]
        if len(seen) == 0:
            assert np.isnan(got)
        else:
            best = max(seen, key=lambda i: (s["week_ending"][i].astype("int64"), s["delivered_at"][i].astype("int64")))
            assert got == s["headcount"][best]


def test_gold_grain_and_ticket_totals():
    cfg, _, _, _, _, (_, silver, gold, _, _) = run()
    ch, tw = gold["gold_cluster_hour"], gold["gold_team_week"]
    assert len(ch["cluster_id"]) == cfg.expected_gold_rows == 245_280
    keys = ch["cluster_id"] * cfg.hours + ch["hour_index"]
    assert len(np.unique(keys)) == len(keys)
    assert len(tw["team_id"]) == 8 * 52
    assert not np.isnan(tw["headcount"]).any() and tw["staffing_missing"].sum() > 0
    inc_tk = silver["tickets"]["ticket_type"] == "incident"
    in_window = (silver["tickets"]["created_utc"] - START) // (7 * 24 * HOUR) < 52
    assert tw["incident_tickets"].sum() == (inc_tk & in_window).sum()


def test_the_strain_signal_survives_the_pipeline():
    _, _, _, _, _, (_, _, gold, _, _) = run()
    tw = gold["gold_team_week"]
    late = tw["week_index"] >= 36
    strained, control = late & (tw["region_id"] == 0), late & (tw["region_id"] == 3)
    assert np.nanmean(tw["overtime_hours_per_head"][strained]) > 1.5 * np.nanmean(tw["overtime_hours_per_head"][control])
    assert np.nanmean(tw["open_backlog_end"][strained]) > 1.5 * np.nanmean(tw["open_backlog_end"][control])
    assert np.nanmean(tw["mean_p99_latency_ms"][strained]) > 1.3 * np.nanmean(tw["mean_p99_latency_ms"][control])
    assert tw["detected_outage_episodes"][strained].sum() > tw["detected_outage_episodes"][control].sum()


def test_every_quality_check_passes():
    *_, (_, _, _, _, checks) = run()
    failed = [c for c in checks if not c[2]]
    assert not failed, failed


def test_tiny_scale_runs_end_to_end():
    cfg, *_, (_, _, gold, _, checks) = run("tiny")
    assert len(gold["gold_cluster_hour"]["cluster_id"]) == cfg.expected_gold_rows
    assert len(gold["gold_team_week"]["team_id"]) == 8 * 4

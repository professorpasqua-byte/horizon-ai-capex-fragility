import numpy as np

from horizon.config import REGIONS, SCALES, SimConfig
from horizon.simulate.telemetry import (
    TEMP_THROTTLE_START_C,
    build_telemetry,
    deferred_maintenance,
    region_week_diversion,
)
from horizon.simulate.world import build_world

CONTROL = [i for i, r in enumerate(REGIONS) if r[2] is None][0]


def make(scale="standard", seed=42):
    cfg = SimConfig(scale=SCALES[scale], seed=seed)
    world = build_world(cfg)
    return cfg, world, build_telemetry(cfg, world)


def same(a, b):
    return a.keys() == b.keys() and all(np.array_equal(a[k], b[k]) for k in a)


def region_of_rows(world, table):
    lookup = dict(zip(world["dim_cluster"]["cluster_id"], world["dim_cluster"]["region_id"]))
    return np.array([lookup[c] for c in table["cluster_id"]])


def test_row_count_matches_gold_grain():
    cfg, _, t = make()
    assert len(t["fact_cluster_hour"]["cluster_id"]) == cfg.expected_gold_rows == 245_280


def test_one_row_per_cluster_hour():
    _, _, t = make()
    f = t["fact_cluster_hour"]
    keys = f["cluster_id"].astype(np.int64) * 100_000 + f["hour_index"]
    assert len(np.unique(keys)) == len(keys)


def test_same_seed_identical_different_seed_differs():
    a, b = make(seed=5)[2], make(seed=5)[2]
    assert same(a["fact_cluster_hour"], b["fact_cluster_hour"])
    c = make(seed=6)[2]
    assert not same(a["fact_cluster_hour"], c["fact_cluster_hour"])


def test_values_are_in_valid_ranges():
    f = make()[2]["fact_cluster_hour"]
    assert f["cpu_util_pct"].min() > 0 and f["cpu_util_pct"].max() <= 100
    assert f["throttle_pct"].min() >= 0 and f["throttle_pct"].max() <= 100
    assert f["packet_drop_pct"].min() > 0
    assert f["p99_latency_ms"].min() > 0


def test_throttling_only_happens_when_hot():
    f = make()[2]["fact_cluster_hour"]
    hot = f["throttle_pct"] > 0
    assert hot.any()
    assert f["inlet_temp_c"][hot].min() >= TEMP_THROTTLE_START_C - 0.01


def test_latency_is_nonlinear_in_utilization():
    f = make()[2]["fact_cluster_hour"]
    u, lat = f["cpu_util_pct"], f["p99_latency_ms"]
    mid = lat[(u >= 40) & (u <= 60)].mean()
    high = lat[u > 85].mean()
    assert high > 3 * mid


def test_daily_peak_follows_local_time():
    _, world, t = make()
    f = t["fact_cluster_hour"]
    region = region_of_rows(world, f)
    offset = REGIONS[0][1]
    local = (f["hour_index"] + offset) % 24
    na = region == 0
    assert f["cpu_util_pct"][na & (local == 15)].mean() > f["cpu_util_pct"][na & (local == 3)].mean()


def test_deferred_maintenance_follows_the_diversion_schedule():
    cfg = SimConfig(scale=SCALES["standard"])
    debt = deferred_maintenance(region_week_diversion(cfg))
    assert np.all(debt[CONTROL] == 0)
    assert np.all(np.diff(debt, axis=1) >= 0)
    assert debt[0, -1] > debt[1, -1] > debt[2, -1] > 0


def test_latent_index_stays_out_of_observed_table():
    _, _, t = make()
    assert "deferred_maintenance_index" not in t["fact_cluster_hour"]
    assert "deferred_maintenance_index" in t["latent_maintenance_week"]


def test_diverting_region_degrades_late_in_the_year_and_control_does_not():
    cfg, world, t = make()
    f = t["fact_cluster_hour"]
    region = region_of_rows(world, f)
    last_q = f["hour_index"] >= cfg.hours * 3 // 4
    na = f["throttle_pct"][(region == 0) & last_q].mean()
    ctrl = f["throttle_pct"][(region == CONTROL) & last_q].mean()
    assert na > ctrl + 1.0
    lat_na = f["p99_latency_ms"][(region == 0) & last_q].mean()
    lat_ctrl = f["p99_latency_ms"][(region == CONTROL) & last_q].mean()
    assert lat_na > 1.5 * lat_ctrl


def test_tiny_scale_runs():
    cfg, _, t = make("tiny")
    assert len(t["fact_cluster_hour"]["cluster_id"]) == cfg.expected_gold_rows == 8 * 28 * 24

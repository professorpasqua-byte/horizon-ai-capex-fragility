from horizon.config import REGIONS, SCALES, SimConfig
from horizon.simulate.budget_staffing import (
    DIVERSION_CAP,
    build_budget,
    build_budget_staffing,
    diversion_share,
    quarter_index,
)
from horizon.simulate.world import build_world

CONTROL = [i for i, r in enumerate(REGIONS) if r[2] is None][0]


def make(scale="standard", seed=42):
    cfg = SimConfig(scale=SCALES[scale], seed=seed)
    world = build_world(cfg)
    return cfg, world, build_budget_staffing(cfg, world)


def test_control_region_never_diverts():
    assert all(diversion_share(CONTROL, q) == 0.0 for q in range(4))


def test_diversion_is_staggered_and_capped():
    assert diversion_share(0, 0) > 0
    assert diversion_share(1, 0) == 0 and diversion_share(1, 1) > 0
    assert diversion_share(2, 1) == 0 and diversion_share(2, 2) > 0
    assert max(diversion_share(r, q) for r in range(4) for q in range(4)) <= DIVERSION_CAP


def test_budget_adds_up():
    b = build_budget(SimConfig(scale=SCALES["standard"]))
    for i in range(len(b["region_id"])):
        total = b["ai_budget_musd"][i] + b["core_budget_musd"][i]
        growth_part = b["total_budget_musd"][i] * 0.40
        assert abs(total + growth_part - b["total_budget_musd"][i]) < 0.02


def test_quarter_index_boundaries():
    from datetime import date

    assert quarter_index(date(2025, 10, 1)) == 0
    assert quarter_index(date(2025, 12, 31)) == 0
    assert quarter_index(date(2026, 1, 1)) == 1
    assert quarter_index(date(2026, 9, 30)) == 3


def test_one_row_per_team_week():
    cfg, world, t = make()
    n_teams = len(world["dim_team"]["team_id"])
    assert len(t["fact_team_week"]["team_id"]) == n_teams * 52
    keys = set(zip(t["fact_team_week"]["team_id"], t["fact_team_week"]["week_index"]))
    assert len(keys) == n_teams * 52


def test_headcount_is_conserved_and_never_tiny():
    _, _, t = make()
    f = t["fact_team_week"]
    for i in range(len(f["team_id"]) - 1):
        if f["team_id"][i] != f["team_id"][i + 1]:
            continue
        expected = f["headcount"][i] - f["departures"][i] - f["reductions"][i] + f["hires"][i]
        assert f["headcount"][i + 1] == expected
    assert min(f["headcount"]) >= 2


def test_same_seed_identical_different_seed_differs():
    assert make(seed=5)[2] == make(seed=5)[2]
    assert make(seed=1)[2] != make(seed=2)[2]


def test_latent_columns_stay_out_of_observed_tables():
    _, _, t = make()
    banned = {"capacity_load_ratio", "load_units", "effective_capacity"}
    for name in ("fact_budget_quarterly", "fact_team_week"):
        assert not banned & set(t[name])
    assert "capacity_load_ratio" in t["latent_team_week"]


def test_planted_tipping_point_is_reachable_and_control_is_safe():
    cfg, world, t = make()
    lat = t["latent_team_week"]
    region_of = dict(zip(world["dim_team"]["team_id"], world["dim_team"]["region_id"]))
    first = {}
    for team, week, ratio in zip(lat["team_id"], lat["week_index"], lat["capacity_load_ratio"]):
        r = region_of[team]
        if r == CONTROL:
            assert ratio > cfg.truth.fracture_ratio
        elif ratio < cfg.truth.fracture_ratio:
            first[r] = min(first.get(r, 999), week)
    assert 0 in first and 1 in first
    assert first[0] < first[1]


def test_tiny_scale_runs():
    cfg, world, t = make("tiny")
    assert len(t["fact_team_week"]["team_id"]) == 8 * 4

from horizon.config import SCALES, SimConfig
from horizon.simulate.world import build_world


def cfg(scale="standard", seed=42):
    return SimConfig(scale=SCALES[scale], seed=seed)


def test_standard_gold_rows():
    assert cfg().expected_gold_rows == 245_280


def test_tiny_scale_size():
    c = cfg("tiny")
    assert c.n_clusters == 8
    assert c.expected_gold_rows == 8 * 28 * 24


def test_every_cluster_has_a_team():
    w = build_world(cfg())
    teams = set(w["dim_team"]["team_id"])
    assert len(w["dim_cluster"]["cluster_id"]) == 28
    assert all(t in teams for t in w["dim_cluster"]["team_id"])


def test_same_seed_identical_world():
    assert build_world(cfg(seed=7)) == build_world(cfg(seed=7))


def test_different_seed_differs():
    assert build_world(cfg(seed=1)) != build_world(cfg(seed=2))


def test_one_control_region():
    assert sum(build_world(cfg())["dim_region"]["is_control"]) == 1


def test_truth_stays_out_of_dimension_tables():
    w = build_world(cfg())
    banned = {"latent_safety", "fracture_ratio", "lag_weeks", "underreport_low_safety"}
    for name in ("dim_region", "dim_team", "dim_cluster"):
        assert not banned & set(w[name])
    assert "latent_safety_by_team" in w["truth"]

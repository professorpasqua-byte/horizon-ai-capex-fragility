import json
import pathlib
import re
import tempfile

import numpy as np

from horizon.analysis import analyze, write_results
from horizon.grading.grade import grade, summarize, true_crossing_weeks
from horizon.models.features import capacity_index
from horizon.models.hinge import poisson_fit
from horizon.simulate.budget_staffing import build_budget_staffing
from test_pipeline import ledger, run

_CACHE = {}


def get():
    if "r" not in _CACHE:
        cfg, world, inc, L, dims, (b, s, g, dq, checks) = run()
        res = analyze(g, s["tickets"], dims, cfg.hours)
        lat = build_budget_staffing(cfg, world)["latent_team_week"]
        rows = grade(res, world["truth"], lat, ledger(L), dq, dims)
        _CACHE["r"] = (cfg, world, g, dims, res, rows, lat)
    return _CACHE["r"]


def test_poisson_fit_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, 3000)
    exposure = rng.integers(1, 5, 3000).astype(float)
    y = rng.poisson(exposure * np.exp(0.5 + 1.2 * x)).astype(float)
    beta, _ = poisson_fit(np.column_stack([np.ones(3000), x]), y, np.log(exposure))
    assert abs(beta[0] - 0.5) < 0.15 and abs(beta[1] - 1.2) < 0.2


def test_capacity_index_starts_near_one_and_falls_where_budget_is_diverted():
    _, _, g, _, _, _, _ = get()
    tw = g["gold_team_week"]
    idx = capacity_index(tw)
    for t in range(8):
        m = tw["team_id"] == t
        assert abs(idx[m][:4].mean() - 1) < 0.08
    late = tw["week_index"] >= 40
    assert idx[late & (tw["region_id"] == 0)].min() < idx[late & (tw["region_id"] == 3)].min() - 0.1


def test_tipping_point_model_finds_the_lead_time_and_a_real_effect():
    _, _, _, _, res, _, _ = get()
    tip = res["tipping"]
    assert abs(tip["lag_weeks"] - 6) <= 2
    assert tip["lr_vs_no_tipping_point"] > 10
    assert 0.5 <= tip["knot"] <= 0.95 and tip["knot_ci"][0] <= tip["knot"] <= tip["knot_ci"][1]
    assert tip["rate_multiplier_at_full_strain"] > 2


def test_early_warning_flags_diverting_teams_and_never_the_control():
    _, _, _, dims, res, _, _ = get()
    ew = res["early"]
    region = dict(zip(dims["dim_team"]["team_id"], dims["dim_team"]["region_id"]))
    for t, f, s in zip(ew["team_id"], ew["flag_week"], ew["surge_week"]):
        if region[int(t)] == 3:
            assert f == -1
        if f >= 0 and s >= 0:
            assert f <= s
    assert (ew["flag_week"] >= 0).sum() >= 4


def test_reporting_gap_finds_the_filing_gap_and_the_right_teams():
    _, world, _, _, res, _, _ = get()
    gap = res["gap"]
    assert gap["low_rate"] < gap["high_rate"] - 0.1
    assert gap["rate_gap_ci"][0] > 0
    safety = world["truth"]["latent_safety_by_team"]
    true_low = np.array([safety[str(int(t))] < 0.5 for t in gap["team_id"]])
    assert np.array_equal(true_low, gap["low_safety"])
    assert gap["unticketed_total"] > 0 and gap["episodes_total"] > gap["unticketed_total"]


def test_grading_reports_hits_and_misses_honestly():
    _, _, _, _, _, rows, _ = get()
    assert {r["verdict"] for r in rows} <= {"hit", "miss"}
    by = {r["metric"]: r for r in rows}
    for metric in ("lead_time_weeks", "control_teams_falsely_flagged", "telemetry_duplicates_removed",
                   "timezone_clusters_found", "filing_rate_low_safety_teams"):
        assert by[metric]["verdict"] == "hit", metric
    s = summarize(rows)
    assert s["total"] == 13 and s["hits"] >= 8 and s["hits"] + len(s["misses"]) == 13


def test_true_crossing_weeks_finds_the_first_week_below_the_line():
    lat = {"team_id": [0] * 5 + [1] * 5, "week_index": list(range(5)) * 2,
           "capacity_load_ratio": [1, 0.9, 0.7, 0.6, 0.5] + [1, 1, 1, 0.9, 0.8]}
    assert true_crossing_weeks(lat, 0.72) == {0: 2, 1: -1}


def test_result_files_are_complete_and_small():
    _, _, g, _, res, rows, _ = get()
    d = pathlib.Path(tempfile.mkdtemp())
    write_results(res, rows, g["gold_team_week"], d)
    names = {p.name for p in d.iterdir()}
    assert {"findings.json", "grading.csv", "tipping_profile.csv", "lead_time_profile.csv",
            "early_warning.csv", "reporting_gap.csv", "team_signals.csv"} <= names
    assert sum(p.stat().st_size for p in d.iterdir()) < 100_000
    f = json.loads((d / "findings.json").read_text())
    assert f["grading"]["total"] == 13 and "tipping" in f and "gap" in f


def test_pipeline_and_models_never_import_the_simulator_or_read_the_truth_folder():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "horizon"
    files = [p for d in ("bronze", "silver", "gold", "models") for p in (root / d).glob("*.py")] + [root / "pipeline.py"]
    for p in files:
        text = p.read_text()
        assert not re.search(r"horizon\.simulate|from horizon import simulate", text), p
        assert 'root / "truth"' not in text and "latent_" not in text.replace("startswith(\"latent_\")", ""), p


def test_analysis_is_deterministic():
    cfg, _, g, dims, res, _, _ = get()
    _, _, _, L, _, (_, s, _, _, _) = run()
    again = analyze(g, s["tickets"], dims, cfg.hours)
    assert again["tipping"]["knot"] == res["tipping"]["knot"] and again["tipping"]["lag_weeks"] == res["tipping"]["lag_weeks"]
    assert again["gap"]["low_rate"] == res["gap"]["low_rate"]

import pathlib
import tempfile

import numpy as np

from dashboard import data
from horizon.analysis import write_results
from test_models import get

ROOT = pathlib.Path(__file__).resolve().parents[1]


def results_dir():
    _, _, g, _, res, rows, _ = get()
    d = pathlib.Path(tempfile.mkdtemp())
    write_results(res, rows, g["gold_team_week"], d)
    for name in ("dq_report.csv", "cleaning_report.csv"):
        (d / name).write_text("a,b\n1,2\n")
    return d


def test_headline_matches_the_findings():
    d = results_dir()
    h = data.headline(d)
    assert h["lag_weeks"] == 6 and h["hits"] + len(h["misses"]) == h["total"] == 13
    assert abs(h["tipping_ratio"] - h["knot_index"] * 1.05) < 0.006
    assert h["true_tipping_ratio"] == 0.72


def test_region_chart_shows_the_control_holding_and_a_diverting_region_falling():
    d = results_dir()
    wide = data.region_index_by_week(d)
    assert wide.shape == (52, 5) and "tipping point" in wide.columns
    assert wide["na-east"].iloc[-8:].mean() < wide["latam-central"].iloc[-8:].mean() - 0.1
    assert data.episodes_by_region_week(d).shape == (52, 4)


def test_budget_view_gets_worse_as_more_budget_moves_to_ai():
    view = data.budget_view(results_dir())
    assert view.index.min() == 0.0 and view.index.max() >= 0.15
    assert view.capacity_index.iloc[-1] < view.capacity_index.iloc[0]
    assert view.team_weeks.sum() > 300


def test_ticket_gap_table_has_one_row_per_team():
    t = data.team_filing(results_dir())
    assert len(t) == 8 and {"filing_rate", "safety_score", "low_safety"} <= set(t.columns)


def test_app_and_pages_compile_and_only_use_the_results_folder():
    files = [ROOT / "app.py"] + sorted((ROOT / "pages").glob("*.py"))
    assert len(files) == 5
    for p in files:
        text = p.read_text()
        compile(text, str(p), "exec")
        assert "horizon." not in text and "data/truth" not in text and "polars" not in text, p
    assert "streamlit" in (ROOT / "requirements.txt").read_text()

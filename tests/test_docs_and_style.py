import pathlib
import re

from dashboard import data
from test_dashboard import results_dir
from test_pipeline import run

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_data_dictionary_documents_every_column():
    _, _, _, L, dims, (_, _, gold, _, _) = run()
    text = (ROOT / "docs" / "DATA_DICTIONARY.md").read_text()
    cols = set()
    for table in list(gold.values()) + [v for k, v in L.items() if not k.startswith("latent_")] + list(dims.values()):
        cols |= set(table)
    missing = sorted(c for c in cols if f"`{c}`" not in text)
    assert not missing, missing


def test_methods_doc_covers_every_stage():
    text = (ROOT / "docs" / "METHODS.md").read_text().lower()
    for word in ("bronze", "silver", "gold", "sql", "tipping point", "lead time", "early warning", "reporting gap", "limits", "reproduce"):
        assert word in text, word


def test_fit_profiles_peak_at_the_chosen_values():
    d = results_dir()
    f = data.findings(d)["tipping"]
    lead, knot = data.lead_time_profile(d), data.tipping_profile(d)
    assert lead.iloc[:, 0].idxmax() == f["lag_weeks"] and lead.iloc[:, 0].min() == 0
    assert abs(knot.iloc[:, 0].idxmax() - f["knot"]) < 1e-9


def test_rolling_outage_chart_is_smoother_than_the_raw_counts():
    d = results_dir()
    smooth, raw = data.episodes_by_region_week(d), data.episodes_by_region_week(d, window=1)
    assert smooth.shape == raw.shape and (smooth.std() < raw.std()).all()


def test_style_module_compiles_and_every_page_uses_the_header():
    compile((ROOT / "dashboard" / "style.py").read_text(), "style.py", "exec")
    for p in [ROOT / "app.py"] + sorted((ROOT / "pages").glob("*.py")):
        text = p.read_text()
        assert "header(" in text and "st.title" not in text, p
        compile(text, str(p), "exec")
    assert "[theme.sidebar]" in (ROOT / ".streamlit" / "config.toml").read_text()


def test_readme_explains_every_file_and_covers_the_real_world_and_the_psychology():
    text = (ROOT / "README.md").read_text()
    files = [p for p in (ROOT / "src" / "horizon").rglob("*.py") if p.name != "__init__.py"]
    files += [p for d in ("tests", "pages", "dashboard") for p in (ROOT / d).glob("*.py") if p.name != "__init__.py"]
    files += list((ROOT / "sql").glob("*.sql")) + list((ROOT / "docs").glob("*.md"))
    files += [ROOT / "app.py", ROOT / "pyproject.toml", ROOT / "requirements.txt"]
    missing = sorted(p.name for p in files if not re.search(rf"[`/]{re.escape(p.name)}`", text))
    assert not missing, missing
    for word in ("Forrester", "AWS", "Azure", "Google Cloud", "Job Demands-Resources", "Conservation of Resources",
                 "Edmondson", "Hobfoll", "as-of", "psychological safety"):
        assert word in text, word

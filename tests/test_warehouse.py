import numpy as np

from horizon.models.features import capacity_index
from horizon.warehouse import SQL_DIR, build_warehouse, run_sql, sql_checks
from test_pipeline import run

try:
    import duckdb  # noqa: F401

    ENGINE = "duckdb"
except ImportError:  # the same SQL is tested on SQLite when DuckDB is not installed
    ENGINE = "sqlite"

_CACHE = {}


def get():
    if "w" not in _CACHE:
        _, world, _, _, dims, (_, _, gold, _, _) = run()
        tables = dict(gold)
        tables.update(dims)
        _CACHE["w"] = (gold, build_warehouse(tables, ENGINE))
    return _CACHE["w"]


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def test_sql_files_exist_and_every_statement_is_plain():
    files = sorted(p.name for p in SQL_DIR.glob("*.sql"))
    assert files == ["01_views.sql", "02_region_quarter.sql", "03_quality_checks.sql"]
    for f in files:
        text = (SQL_DIR / f).read_text()
        assert "read_parquet" not in text and "::" not in text and "QUALIFY" not in text.upper()


def test_warehouse_holds_the_full_gold_grain():
    _, con = get()
    assert one(con, "SELECT COUNT(*) FROM gold_cluster_hour") == 245_280
    assert one(con, "SELECT COUNT(*) FROM gold_team_week") == 8 * 52
    assert one(con, "SELECT COUNT(*) FROM dim_cluster") == 28


def test_missing_values_become_null_so_sql_averages_work():
    gold, con = get()
    want = int(np.isnan(gold["gold_cluster_hour"]["headcount_known"]).sum())
    assert one(con, "SELECT COUNT(*) FROM gold_cluster_hour WHERE headcount_known IS NULL") == want
    avg = one(con, "SELECT AVG(p99_latency_ms) FROM gold_cluster_hour")
    assert abs(avg - np.nanmean(gold["gold_cluster_hour"]["p99_latency_ms"])) < 1e-6


def test_sql_capacity_index_equals_the_python_one():
    gold, con = get()
    rows = con.execute("SELECT team_id, week_index, capacity_index FROM team_week_features ORDER BY team_id, week_index").fetchall()
    sql_idx = np.array([r[2] for r in rows])
    py_idx = capacity_index(gold["gold_team_week"])
    assert len(sql_idx) == len(py_idx) == 416
    assert np.allclose(sql_idx, py_idx, atol=1e-9)


def test_every_sql_quality_check_passes():
    _, con = get()
    checks = sql_checks(con)
    assert len(checks) == 10
    assert all(c[2] for c in checks), [c for c in checks if not c[2]]


def test_region_quarter_summary_matches_python_and_shows_the_pattern():
    gold, con = get()
    rows = run_sql(con, "02_region_quarter.sql")
    assert len(rows) == 16
    assert sum(r["outage_episodes"] for r in rows) == gold["gold_team_week"]["detected_outage_episodes"].sum()
    last = {r["region_id"]: r["avg_capacity_index"] for r in rows if r["quarter"] == 3}
    assert last[0] < last[3] - 0.1

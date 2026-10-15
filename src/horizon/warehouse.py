"""Load the gold tables into a database and run the SQL in sql/.

DuckDB is the real engine. SQLite runs the very same SQL in tests where DuckDB
is not installed. NaN becomes NULL on the way in, so SQL averages behave.
"""

import argparse
import csv
from pathlib import Path

import numpy as np

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect(engine="duckdb", path=":memory:"):
    if engine == "duckdb":
        import duckdb

        return duckdb.connect(str(path))
    import sqlite3

    return sqlite3.connect(str(path))


def _arrow(col):
    import pyarrow as pa

    a = np.asarray(col)
    return pa.array(a, mask=np.isnan(a)) if a.dtype.kind == "f" else pa.array(a)


def load(con, engine, tables):
    for name, t in tables.items():
        if engine == "duckdb":
            import pyarrow as pa

            con.register(f"{name}_src", pa.table({k: _arrow(v) for k, v in t.items()}))
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name}_src")
            con.unregister(f"{name}_src")
        else:
            cols = [k for k, v in t.items() if np.asarray(v).dtype.kind != "M"]
            con.execute(f"CREATE TABLE {name} ({', '.join(cols)})")
            data = [[None if (isinstance(x, float) and x != x) else x for x in np.asarray(t[k]).tolist()] for k in cols]
            con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * len(cols))})", zip(*data))


def _body(stmt):
    return "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--")).strip()


def run_sql(con, filename):
    """Run every statement in a SQL file. Returns the rows of the last SELECT as dicts."""
    rows = []
    for stmt in (_body(s) for s in (SQL_DIR / filename).read_text().split(";")):
        if not stmt:
            continue
        cur = con.execute(stmt)
        if stmt.upper().startswith("SELECT"):
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows


def build_warehouse(tables, engine="duckdb", path=":memory:"):
    con = connect(engine, path)
    load(con, engine, tables)
    run_sql(con, "01_views.sql")
    return con


def sql_checks(con):
    return [(r["table_name"], r["check_name"], bool(r["passed"]), r["detail"]) for r in run_sql(con, "03_quality_checks.sql")]


def main():
    from horizon.pipeline import read_table

    parser = argparse.ArgumentParser(description="Build the DuckDB warehouse and run the SQL.")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    args = parser.parse_args()
    tables = {p.stem: read_table(p) for p in sorted((args.root / "gold").glob("*.parquet"))}
    tables.update({p.stem: read_table(p) for p in sorted((args.root / "raw" / "dims").glob("*.parquet"))})
    con = build_warehouse(tables, "duckdb", args.root / "warehouse.duckdb")
    checks = sql_checks(con)
    quarters = run_sql(con, "02_region_quarter.sql")
    args.results.mkdir(parents=True, exist_ok=True)
    for fname, rows in (("sql_checks.csv", [dict(table_name=a, check_name=b, passed=int(c), detail=d) for a, b, c, d in checks]),
                        ("region_quarter.csv", quarters)):
        with open(args.results / fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows])
    for table, check, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {table}.{check} {detail}")
    print(f"region_quarter rows={len(quarters)}  warehouse={args.root / 'warehouse.duckdb'}")


if __name__ == "__main__":
    main()

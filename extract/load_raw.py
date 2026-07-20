"""Load the extraction CSVs into the DuckDB warehouse as raw.* tables.

This script is standalone on purpose, so a reviewer without an API key can
load the committed CSVs and run dbt against them without re-running the
extraction.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = REPO_ROOT / "data" / "extracted"
DB_PATH = REPO_ROOT / "dbt" / "target" / "portfolio.duckdb"

TABLES = ["raw_extractions", "document_notes"]


def load() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("create schema if not exists raw")
    for table in TABLES:
        csv_path = CSV_DIR / f"{table}.csv"
        con.execute(
            f"create or replace table raw.{table} as select * from read_csv(?)",
            [str(csv_path)],
        )
        n = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
        print(f"loaded raw.{table}: {n} rows -> {DB_PATH.name}")
    con.close()


if __name__ == "__main__":
    load()

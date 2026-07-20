"""Load the extraction CSVs into the DuckDB warehouse as raw.* tables.

Loading is append-only with a batch stamp. Rows from source files that are
already in the warehouse are skipped, and every inserted row carries a
loaded_at timestamp, which is what the incremental fact build uses to find
the grain keys it needs to rebuild. A re-extraction that changes rows for
an already-loaded file will therefore not propagate on its own; run
`make rebuild` for a full refresh from the CSVs.

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
        csv_path = str(CSV_DIR / f"{table}.csv")
        con.execute(
            f"""
            create table if not exists raw.{table} as
            select *, current_timestamp as loaded_at
            from read_csv(?) limit 0
            """,
            [csv_path],
        )
        inserted = con.execute(
            f"""
            insert into raw.{table}
            select *, current_timestamp
            from read_csv(?) c
            where c.source_file not in (select source_file from raw.{table})
            """,
            [csv_path],
        ).fetchone()[0]
        total = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
        print(f"raw.{table}: {inserted} new rows loaded, {total} total")
    con.close()


if __name__ == "__main__":
    load()

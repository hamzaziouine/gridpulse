"""Date dimension, replaceWhere predicates, the commit-charge guard and reference specs."""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from gridpulse import hostguard, reference
from gridpulse.dims import date_dimension
from gridpulse.lakehouse import file_names, replace_predicate, sql_literal

ROOT = Path(__file__).parents[2]


def test_date_dimension_holidays_and_business_days() -> None:
    d = date_dimension(date(2025, 7, 30), date(2025, 8, 5)).set_index("est_date")
    civic = d.loc[date(2025, 8, 4)]  # first Monday of August
    assert civic["holiday_name"] == "Civic Holiday" and not civic["is_business_day"]
    assert d.loc[date(2025, 8, 2), "is_weekend"] and not d.loc[date(2025, 8, 2), "is_business_day"]
    assert d.loc[date(2025, 8, 5), "is_business_day"]
    assert d.loc[date(2025, 8, 5), "date_key"] == 20250805
    assert set(d["season"]) == {"Summer"}
    assert len(d) == 7


def test_date_dimension_christmas_and_seasons() -> None:
    d = date_dimension(date(2025, 12, 24), date(2026, 3, 1)).set_index("est_date")
    assert d.loc[date(2025, 12, 25), "holiday_name"] == "Christmas Day"
    assert d.loc[date(2025, 12, 26), "holiday_name"] == "Boxing Day"
    assert d.loc[date(2026, 2, 28), "season"] == "Winter"
    assert d.loc[date(2026, 3, 1), "season"] == "Spring"


def test_sql_literals_and_predicate() -> None:
    assert sql_literal(5) == "5"
    assert sql_literal("it's") == "'it''s'"
    assert sql_literal(date(2026, 11, 7)) == "DATE '2026-11-07'"
    assert sql_literal(datetime(2026, 11, 7, 5)) == "TIMESTAMP '2026-11-07 05:00:00'"
    pred = replace_predicate({"source_file": ["a.csv", "b.csv"], "run_date": [date(2026, 1, 2)]})
    assert pred == "`source_file` IN ('a.csv', 'b.csv') AND `run_date` IN (DATE '2026-01-02')"
    with pytest.raises(ValueError):
        replace_predicate({"source_file": []})


def test_file_names_handles_urls_and_windows_paths() -> None:
    assert file_names(["abfss://ws@onelake.dfs.fabric.microsoft.com/lh/Files/bronze/a.csv",
                       r"C:\data\raw\b.json"]) == ["a.csv", "b.json"]  # fmt: skip


@pytest.mark.skipif(sys.platform != "win32", reason="Windows commit charge only")
def test_commit_gb_is_plausible() -> None:
    used = hostguard.commit_gb()
    assert used is not None and 0.5 < used < 1024


def test_watchdog_calls_breach_handler() -> None:
    hits: list[float] = []
    dog = hostguard.CommitWatchdog(limit_gb=-1.0, interval_s=0.01, on_breach=hits.append)
    if hostguard.commit_gb() is None:
        pytest.skip("no commit charge on this platform")
    dog.start()
    dog.join(timeout=5)
    assert hits and hits[0] > 0


def test_reference_specs_match_the_tsql_schema_and_csvs() -> None:
    ddl = (ROOT / "sql" / "001_schema.sql").read_text(encoding="utf-8")
    for table in reference.LOAD_ORDER:
        body = re.search(rf"CREATE TABLE dbo\.{table} \((.*?)\n\);", ddl, re.S)
        assert body, table
        sql_cols = re.findall(r"^\s{4}(\w+)\s", body.group(1), re.M)
        assert sql_cols == reference.columns(table)
        header = (ROOT / "data" / "reference" / f"{table}.csv").read_text("utf-8").splitlines()[0]
        assert header.split(",") == reference.columns(table)

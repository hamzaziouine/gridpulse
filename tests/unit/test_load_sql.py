"""scripts/load_sql.py against SQLite (foreign keys on) and its T-SQL handling."""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("load_sql", ROOT / "scripts" / "load_sql.py")
assert spec and spec.loader
load_sql = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load_sql)


def fresh(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "ref.db")
    conn.execute("PRAGMA foreign_keys = ON")
    for s in load_sql.sqlite_ddl():
        conn.execute(s)
    return conn


def test_schema_splits_into_go_batches() -> None:
    batches = load_sql.split_batches((ROOT / "sql" / "001_schema.sql").read_text("utf-8"))
    assert len(batches) == 3
    assert batches[0].startswith("-- GridPulse") or "DROP TABLE" in batches[0]
    assert all(not re.search(r"^\s*GO\s*$", b, re.M | re.I) for b in batches)
    assert "ADD SENSITIVITY CLASSIFICATION" in batches[2]


def test_load_is_idempotent_and_counts_match(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    rows = load_sql.read_rows()
    assert load_sql.load(conn, rows) == {"sites": 10, "customers": 50, "meters": 50}
    assert load_sql.verify(conn) == load_sql.EXPECTED
    load_sql.load(conn, rows)  # rerun
    assert load_sql.verify(conn) == load_sql.EXPECTED
    maintenance = conn.execute("SELECT COUNT(*) FROM meters WHERE status='maintenance'").fetchone()
    assert maintenance[0] == 2  # every 17th meter (MTR-0017, MTR-0034)


def test_failed_load_rolls_back(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    rows = load_sql.read_rows()
    load_sql.load(conn, rows)
    broken = dict(rows)
    broken["meters"] = [*rows["meters"], ("MTR-9999", 999, 1, "2020-01-01", "TOU", 10, "active")]
    with pytest.raises(sqlite3.IntegrityError):
        load_sql.load(conn, broken)  # site 999 does not exist
    assert load_sql.verify(conn) == load_sql.EXPECTED  # previous contents intact


def test_cli_sqlite_and_dry_run(tmp_path: Path, capsys) -> None:
    assert load_sql.main(["--sqlite", str(tmp_path / "cli.db")]) == 0
    assert load_sql.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "nothing sent anywhere" in out and "schema batches: 3" in out


def test_password_never_from_argv() -> None:
    with pytest.raises(SystemExit):
        load_sql.main(["--server", "x", "--password", "hunter2"])
    cs = load_sql.azure_connection_string("s.database.windows.net", "db", None, None, entra=True)
    assert "ActiveDirectoryDefault" in cs and "Pwd" not in cs and "Encrypt=yes" in cs
    with pytest.raises(ValueError):
        load_sql.azure_connection_string("s", "db", "gpadmin", None, entra=False)


def test_seed_sql_matches_the_csvs() -> None:
    seed = (ROOT / "sql" / "002_seed.sql").read_text("utf-8")
    for table, n in load_sql.EXPECTED.items():
        assert seed.count(f"INSERT INTO dbo.{table} ") == n


def test_connection_string_uses_only_keywords_the_driver_accepts() -> None:
    # mssql-python validates keywords against an allowlist; "Connection Timeout" was rejected on
    # the first real Azure run (11-23), so both auth variants go through the driver's own parser.
    parser_mod = pytest.importorskip("mssql_python.connection_string_parser")
    parser = parser_mod._ConnectionStringParser(validate_keywords=True)
    for cs in (
        load_sql.azure_connection_string("s.database.windows.net", "db", None, None, entra=True),
        load_sql.azure_connection_string("s.database.windows.net", "db", "u", "p", entra=False),
    ):
        parser._parse(cs)

"""T2.1: load the S3 reference data (sites, customers, meters) into Azure SQL Database.

Azure SQL (needs `uv sync --extra sql`, the server from infra/azure/deploy.ps1, and a laptop IP
allowed by the SQL firewall):

    uv run python scripts/load_sql.py --schema \\
        --server sql-hz2611-cdda.database.windows.net --database sqldb-hz2611-gridpulse \\
        --user gpadmin --kv-url https://kv-hz2611-cdda.vault.azure.net \\
        --kv-secret sql-gpadmin-password

    # or as yourself, no password at all (Entra contained user, e.g. the Data Engineer persona):
    uv run python scripts/load_sql.py --server ... --database ... --entra

1. The SQL admin password is read from Key Vault with DefaultAzureCredential (your `az login`).
   It is never taken from the command line, a file or an environment variable.
2. `--schema` runs sql/001_schema.sql batch by batch (split on GO): it drops and recreates the
   three tables and their sensitivity classifications.
3. The rows of data/reference/*.csv replace the table contents in ONE transaction (children
   deleted first, parents inserted first), with parameterised inserts. Rerunning gives the same
   10 / 50 / 50 rows.
4. Counts are checked, and on Azure SQL the classified columns are listed.

Local: `--sqlite path.db` creates equivalent tables (foreign keys on) and runs steps 3 and 4;
that is what the tests do. `--dry-run` parses and validates everything and connects to nothing.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gridpulse import reference  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "sql" / "001_schema.sql"
REF_DIR = ROOT / "data" / "reference"
EXPECTED = {"sites": 10, "customers": 50, "meters": 50}
_GO = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


def split_batches(sql_text: str) -> list[str]:
    """T-SQL script -> batches, split on lines that hold only GO (as sqlcmd/SSMS do)."""
    return [b.strip() for b in _GO.split(sql_text) if b.strip() and not _only_comments(b)]


def _only_comments(batch: str) -> bool:
    return all(not ln.strip() or ln.strip().startswith("--") for ln in batch.splitlines())


def convert(value: str, sqlite_type: str) -> Any:
    if value == "":
        return None
    if sqlite_type == "INTEGER":
        return int(value)
    if sqlite_type == "REAL":
        return float(value)
    return value  # TEXT, incl. ISO dates (SQL Server converts 'YYYY-MM-DD' to DATE)


def read_rows(folder: Path = REF_DIR) -> dict[str, list[tuple[Any, ...]]]:
    out: dict[str, list[tuple[Any, ...]]] = {}
    for table in reference.LOAD_ORDER:
        spec = reference.TABLES[table]
        with (folder / f"{table}.csv").open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != [c for c, _, _ in spec]:
                raise ValueError(f"{table}.csv columns {reader.fieldnames} != spec")
            out[table] = [tuple(convert(r[c], st) for c, _, st in spec) for r in reader]
    return out


def sqlite_ddl() -> list[str]:
    fks = {"meters": ["FOREIGN KEY (site_id) REFERENCES sites (site_id)",
                      "FOREIGN KEY (customer_id) REFERENCES customers (customer_id)"]}  # fmt: skip
    stmts = [f"DROP TABLE IF EXISTS {t}" for t in reference.DELETE_ORDER]
    for t in reference.LOAD_ORDER:
        cols = [f"{c} {st}" for c, _, st in reference.TABLES[t]]
        cols.append(f"PRIMARY KEY ({reference.PRIMARY_KEYS[t]})")
        cols += fks.get(t, [])
        stmts.append(f"CREATE TABLE {t} ({', '.join(cols)})")
    return stmts


def load(conn: Any, rows: dict[str, list[tuple[Any, ...]]], prefix: str = "") -> dict[str, int]:
    """Replace the contents of the three tables in one transaction; returns rows inserted."""
    cur = conn.cursor()
    try:
        for t in reference.DELETE_ORDER:
            cur.execute(f"DELETE FROM {prefix}{t}")  # noqa: S608 - table names from a constant
        for t in reference.LOAD_ORDER:
            cols = reference.columns(t)
            marks = ", ".join("?" for _ in cols)
            sql = f"INSERT INTO {prefix}{t} ({', '.join(cols)}) VALUES ({marks})"  # noqa: S608
            cur.executemany(sql, rows[t])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {t: len(rows[t]) for t in reference.LOAD_ORDER}


def verify(conn: Any, prefix: str = "") -> dict[str, int]:
    cur = conn.cursor()
    counts = {}
    for t in reference.LOAD_ORDER:
        cur.execute(f"SELECT COUNT(*) FROM {prefix}{t}")  # noqa: S608
        counts[t] = int(cur.fetchone()[0])
    if counts != EXPECTED:
        raise RuntimeError(f"unexpected row counts {counts}, expected {EXPECTED}")
    return counts


def classifications(conn: Any) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT OBJECT_NAME(major_id), COL_NAME(major_id, minor_id), CAST(label AS NVARCHAR(128)) "
        "FROM sys.sensitivity_classifications ORDER BY 1, 2"
    )
    return [tuple(r) for r in cur.fetchall()]


def kv_secret(vault_url: str, name: str) -> str:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    value = SecretClient(vault_url, DefaultAzureCredential()).get_secret(name).value
    if not value:
        raise SystemExit(f"Key Vault secret {name} is empty")
    return value


def azure_connection_string(server: str, database: str, user: str | None, password: str | None,
                            entra: bool) -> str:  # fmt: skip
    base = (f"Server=tcp:{server},1433;Database={database};Encrypt=yes;"
            "TrustServerCertificate=no;Connection Timeout=30;")  # fmt: skip
    if entra:
        return base + "Authentication=ActiveDirectoryDefault;"
    if not (user and password):
        raise ValueError("SQL authentication needs --user and a Key Vault password")
    return base + f"Uid={user};Pwd={password};"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--server", help="e.g. sql-hz2611-cdda.database.windows.net")
    target.add_argument("--sqlite", type=Path, help="local SQLite file (tests, demos)")
    target.add_argument("--dry-run", action="store_true", help="validate, connect to nothing")
    ap.add_argument("--database", default="sqldb-hz2611-gridpulse")
    ap.add_argument("--user", default="gpadmin")
    ap.add_argument("--kv-url", default="https://kv-hz2611-cdda.vault.azure.net")
    ap.add_argument("--kv-secret", default="sql-gpadmin-password")
    ap.add_argument("--entra", action="store_true", help="Entra ID auth, no password")
    ap.add_argument("--schema", action="store_true", help="(re)create tables from 001_schema.sql")
    a = ap.parse_args(argv)

    rows = read_rows()
    batches = split_batches(SCHEMA_SQL.read_text(encoding="utf-8"))
    print(f"rows: { {t: len(r) for t, r in rows.items()} }, schema batches: {len(batches)}")

    if a.dry_run:
        import sqlparse

        for i, b in enumerate(batches, 1):
            n = len([s for s in sqlparse.parse(b) if str(s).strip()])
            print(f"  batch {i}: {n} statement(s), first line: {b.splitlines()[0][:70]}")
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        for s in sqlite_ddl():
            conn.execute(s)
        load(conn, rows)
        print(f"dry run OK (in-memory SQLite): {verify(conn)}; nothing sent anywhere")
        return 0

    if a.sqlite:
        conn = sqlite3.connect(a.sqlite)
        conn.execute("PRAGMA foreign_keys = ON")
        if (
            a.schema
            or not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sites'"
            ).fetchone()
        ):
            for s in sqlite_ddl():
                conn.execute(s)
        print(f"inserted {load(conn, rows)}; verified {verify(conn)} in {a.sqlite}")
        conn.close()
        return 0

    import mssql_python

    password = None if a.entra else kv_secret(a.kv_url, a.kv_secret)
    conn = mssql_python.connect(
        azure_connection_string(a.server, a.database, a.user, password, a.entra)
    )
    try:
        if a.schema:
            cur = conn.cursor()
            for b in batches:
                cur.execute(b)
            conn.commit()
            print(f"schema: {len(batches)} batches executed")
        print(f"inserted {load(conn, rows, prefix='dbo.')}")
        print(f"verified {verify(conn, prefix='dbo.')}")
        for table, column, label in classifications(conn):
            print(f"  classified {table}.{column}: {label}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

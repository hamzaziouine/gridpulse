"""S3 reference tables (Azure SQL `dbo.sites`, `dbo.customers`, `dbo.meters`): one column spec
shared by the SQL loader (scripts/load_sql.py) and the local stand-in for the pipeline's
SQL-to-Lakehouse copy (scripts/run_local.py). sql/001_schema.sql is the T-SQL source of truth;
tests/unit/test_dims_lakehouse_guard.py checks that the two agree.
"""

from __future__ import annotations

# (column, Spark type as the Fabric Copy activity lands it, SQLite type for local tests)
TABLES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "sites": (
        ("site_id", "int", "INTEGER"),
        ("site_code", "string", "TEXT"),
        ("site_name", "string", "TEXT"),
        ("city", "string", "TEXT"),
        ("latitude", "decimal(8,5)", "REAL"),
        ("longitude", "decimal(8,5)", "REAL"),
        ("capacity_kw", "int", "INTEGER"),
    ),
    "customers": (
        ("customer_id", "int", "INTEGER"),
        ("full_name", "string", "TEXT"),
        ("email", "string", "TEXT"),
        ("phone", "string", "TEXT"),
        ("street_address", "string", "TEXT"),
        ("city", "string", "TEXT"),
        ("postal_code", "string", "TEXT"),
        ("segment", "string", "TEXT"),
        ("created_at", "date", "TEXT"),
    ),
    "meters": (
        ("meter_id", "string", "TEXT"),
        ("site_id", "int", "INTEGER"),
        ("customer_id", "int", "INTEGER"),
        ("install_date", "date", "TEXT"),
        ("tariff", "string", "TEXT"),
        ("rated_kw", "int", "INTEGER"),
        ("status", "string", "TEXT"),
    ),
}
PRIMARY_KEYS = {"sites": "site_id", "customers": "customer_id", "meters": "meter_id"}
LOAD_ORDER = ("sites", "customers", "meters")  # parents before children (foreign keys)
DELETE_ORDER = tuple(reversed(LOAD_ORDER))


def columns(table: str) -> list[str]:
    return [c for c, _, _ in TABLES[table]]


def spark_ddl(table: str) -> str:
    return ", ".join(f"`{c}` {t}" for c, t, _ in TABLES[table])


def read_csv(spark, folder: str, table: str):
    """data/reference/<table>.csv -> Spark DataFrame with the types the SQL copy produces."""
    return (
        spark.read.option("header", True)
        .option("mode", "FAILFAST")
        .option("dateFormat", "yyyy-MM-dd")
        .schema(spark_ddl(table))
        .csv(f"{folder}/{table}.csv")
    )

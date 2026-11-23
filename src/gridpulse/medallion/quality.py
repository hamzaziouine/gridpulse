"""Data-quality checks run by nb_silver; results go to `silver_dq_results` (one row per check).

Status: PASS, WARN (a known or expected condition, e.g. the documented 2025-05-01 HE1 gap or the
newest hours waiting for weather), FAIL (the notebook raises after writing the results, so the
pipeline takes its failure path and sends the alert).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from gridpulse.config import CITIES, VARIABLES
from gridpulse.medallion.silver import PII_COLUMNS, valid_demand_rows
from gridpulse.timeutil import est_date

# Hours IESO never published (Market Renewal go-live, PUB_Demand_2025 has no 2025-05-01 HE1).
KNOWN_DEMAND_GAPS: frozenset[datetime] = frozenset({datetime(2025, 5, 1, 5, tzinfo=UTC)})
DEMAND_RANGE_MW = (5_000.0, 30_000.0)  # Ontario demand 2019-2026 was 9,831..25,646 MW
RANGES = {
    "temperature_2m": (-50.0, 50.0),
    "apparent_temperature": (-60.0, 60.0),
    "relative_humidity_2m": (0.0, 100.0),
    "dew_point_2m": (-60.0, 40.0),
    "wind_speed_10m": (0.0, 200.0),
    "cloud_cover": (0.0, 100.0),
    "shortwave_radiation": (0.0, 1_400.0),
    "precipitation": (0.0, 200.0),
    "snowfall": (0.0, 100.0),
}
FRESHNESS_WARN_DAYS, FRESHNESS_FAIL_DAYS = 2, 4
WEATHER_TAIL_HOURS = 72  # demand hours newer than this may still wait for weather

DQ_SCHEMA = T.StructType(
    [
        T.StructField("run_id", T.StringType(), False),
        T.StructField("run_date", T.DateType(), False),
        T.StructField("checked_at", T.TimestampType(), False),
        T.StructField("layer", T.StringType(), False),
        T.StructField("table_name", T.StringType(), False),
        T.StructField("check_name", T.StringType(), False),
        T.StructField("status", T.StringType(), False),
        T.StructField("observed", T.DoubleType(), True),
        T.StructField("expected", T.StringType(), True),
        T.StructField("details", T.StringType(), True),
    ]
)


@dataclass(frozen=True)
class CheckResult:
    table_name: str
    check_name: str
    status: str
    observed: float | None
    expected: str
    details: str = ""


def _r(table: str, check: str, ok: bool, observed: float | None, expected: str, details: str = "",
       warn: bool = False) -> CheckResult:  # fmt: skip
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    return CheckResult(table, check, status, observed, expected, details)


def check_bronze_ieso(bronze: DataFrame) -> list[CheckResult]:
    bad = bronze.where(~valid_demand_rows()).count()
    return [_r("bronze_ieso_demand", "invalid_rows", bad == 0, bad, "0",
               "null date/demand or hour_ending outside 1..24")]  # fmt: skip


def check_demand(bronze: DataFrame, silver: DataFrame, run_date: date) -> list[CheckResult]:
    t = "silver_demand_hourly"
    out: list[CheckResult] = []
    stats = silver.agg(
        F.count("*").alias("n"),
        F.countDistinct("target_time").alias("n_distinct"),
        F.max("est_date").alias("dmax"),
        F.sum(
            (~F.col("ontario_demand_mw").between(*DEMAND_RANGE_MW)).cast("int")
        ).alias("out_of_range"),
    ).first()
    n_bronze_valid = bronze.where(valid_demand_rows()).count()
    out.append(_r(t, "revisions_deduplicated", True, n_bronze_valid - stats["n"], "info",
                  f"{n_bronze_valid} valid bronze rows -> {stats['n']} unique hours"))  # fmt: skip
    out.append(_r(t, "unique_target_time", stats["n"] == stats["n_distinct"],
                  stats["n"] - stats["n_distinct"], "0 duplicates"))  # fmt: skip
    lo, hi = DEMAND_RANGE_MW
    out.append(_r(t, "demand_range", stats["out_of_range"] == 0, stats["out_of_range"],
                  f"{lo:.0f}..{hi:.0f} MW"))  # fmt: skip

    # Hour-level gaps on the continuous grid, built and compared inside Spark. Timestamps leave
    # Spark only as epoch seconds: collect() would turn them into naive local-time datetimes.
    grid = silver.agg(F.min("target_time").alias("a"), F.max("target_time").alias("b")).select(
        F.explode(F.expr("sequence(a, b, interval 1 hour)")).alias("t")
    )
    missing = [
        datetime.fromtimestamp(r["s"], UTC)
        for r in grid.join(silver.select(F.col("target_time").alias("t")), "t", "left_anti")
        .select(F.unix_seconds("t").alias("s"))
        .orderBy("s")
        .collect()
    ]
    unknown = [m for m in missing if m not in KNOWN_DEMAND_GAPS]
    shown = ", ".join(m.strftime("%Y-%m-%d %H:%MZ") for m in missing[:5])
    out.append(_r(t, "hourly_gaps", not missing, len(missing), "0 (known: 2025-05-01 05:00Z)",
                  shown, warn=not unknown))  # fmt: skip

    # Days that do not have 24 hours, except the newest day (IESO posts it hour by hour).
    per_day = silver.groupBy("est_date").count().where(
        (F.col("count") != 24) & (F.col("est_date") < stats["dmax"])
    )
    short_days = [r["est_date"] for r in per_day.orderBy("est_date").collect()]
    known_days = {est_date(g) for g in KNOWN_DEMAND_GAPS}  # the EST day, not the UTC date
    out.append(_r(t, "hours_per_day_24", not short_days, len(short_days),
                  "24 hours per EST day", ", ".join(map(str, short_days[:5])),
                  warn=set(short_days) <= known_days))  # fmt: skip

    lag = (run_date - stats["dmax"]).days
    out.append(_r(t, "freshness_days", lag <= FRESHNESS_WARN_DAYS, lag,
                  f"<= {FRESHNESS_WARN_DAYS} days behind run_date",
                  f"newest EST date {stats['dmax']}", warn=lag <= FRESHNESS_FAIL_DAYS))  # fmt: skip
    return out


def check_weather(bronze_om: DataFrame, silver_city: DataFrame) -> list[CheckResult]:
    t = "silver_weather_city_hourly"
    unmatched = bronze_om.where(F.col("city_key").isNull()).count()
    out = [_r("bronze_openmeteo_hourly", "unmatched_location", unmatched == 0, unmatched, "0",
              "grid point matched no configured city")]  # fmt: skip
    incomplete = (
        silver_city.groupBy("valid_time").count().where(F.col("count") != len(CITIES)).count()
    )
    out.append(_r(t, "cities_per_hour", incomplete == 0, incomplete,
                  f"{len(CITIES)} cities every hour"))  # fmt: skip
    null_exprs = [F.sum(F.col(v).isNull().cast("int")).alias(v) for v in VARIABLES]
    range_exprs = [
        F.sum((~F.col(v).between(lo, hi)).cast("int")).alias(f"rng_{v}")
        for v, (lo, hi) in RANGES.items()
    ]
    row = silver_city.agg(F.count("*").alias("n"), *null_exprs, *range_exprs).first()
    nulls = sum(row[v] or 0 for v in VARIABLES)
    cells = max(1, row["n"] * len(VARIABLES))
    out.append(_r(t, "null_cells", nulls == 0, nulls, "0", f"{100 * nulls / cells:.3f} % of cells",
                  warn=nulls / cells <= 0.01))  # fmt: skip
    bad = {v: row[f"rng_{v}"] or 0 for v in RANGES}
    n_bad = sum(bad.values())
    out.append(_r(t, "physical_ranges", n_bad == 0, n_bad, "all values in physical ranges",
                  ", ".join(f"{k}={v}" for k, v in bad.items() if v)))  # fmt: skip
    return out


def check_join(joined: DataFrame) -> list[CheckResult]:
    t = "silver_demand_weather_hourly"
    tmax_s = joined.agg(F.max(F.unix_seconds("target_time"))).first()[0]
    cutoff_s = tmax_s - WEATHER_TAIL_HOURS * 3600
    no_wx = joined.where(F.col("temperature_2m_w").isNull())
    n_all = no_wx.count()
    n_old = no_wx.where(F.unix_seconds("target_time") < F.lit(cutoff_s)).count()
    return [_r(t, "weather_coverage", n_all == 0, n_all,
               "every demand hour has weather",
               f"{n_all} hours without weather, {n_old} older than {WEATHER_TAIL_HOURS} h",
               warn=n_old == 0)]  # fmt: skip


def check_reference(
    sites: DataFrame, meters_bronze: DataFrame, customers_bronze: DataFrame,
    customers_pseudo: DataFrame, meters_silver: DataFrame,
) -> list[CheckResult]:  # fmt: skip
    orphan_site = meters_bronze.join(sites, "site_id", "left_anti").count()
    orphan_cust = meters_bronze.join(customers_bronze, "customer_id", "left_anti").count()
    dup_email = customers_bronze.groupBy("email").count().where(F.col("count") > 1).count()
    bad_status = meters_silver.where(
        ~F.col("status").isin("active", "maintenance", "retired")
    ).count()
    leaked = sorted(
        set(PII_COLUMNS) & (set(customers_pseudo.columns) | set(meters_silver.columns))
    )
    return [
        _r("silver_meters", "fk_site", orphan_site == 0, orphan_site, "0 orphan meters"),
        _r("silver_meters", "fk_customer", orphan_cust == 0, orphan_cust, "0 orphan meters"),
        _r("silver_meters", "status_domain", bad_status == 0, bad_status,
           "active|maintenance|retired"),  # fmt: skip
        _r("bronze_customers", "email_unique", dup_email == 0, dup_email, "0 duplicates"),
        _r("silver_customers_pseudo", "pii_absent", not leaked, len(leaked),
           "no PII column in silver", ", ".join(leaked)),  # fmt: skip
    ]


def results_frame(
    spark: SparkSession,
    results: list[CheckResult],
    run_id: str,
    run_date: date,
    checked_at: datetime,
    layer: str = "silver",
) -> DataFrame:
    rows = [
        (run_id, run_date, checked_at, layer, r.table_name, r.check_name, r.status,
         None if r.observed is None else float(r.observed), r.expected, r.details)
        for r in results
    ]  # fmt: skip
    return spark.createDataFrame(rows, DQ_SCHEMA)


def failures(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.status == "FAIL"]

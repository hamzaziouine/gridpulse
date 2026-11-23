"""Bronze: raw landed files -> typed Delta rows plus lineage. No business logic here.

Landing zone (written by the Data Factory pipeline, `Files/bronze/` of lh_gridpulse):
- `ieso/PUB_Demand_YYYY.csv` (one file per year; the unsuffixed name is IESO's latest version,
  a manually uploaded `PUB_Demand_YYYY_vNNN.csv` is accepted too),
- `openmeteo/YYYY-MM.json` (Historical Forecast API, one file per month, 5 cities),
- `openmeteo_forecast/YYYY-MM-DD.json` (Forecast API, next days, one file per run date),
- `openmeteo_prevruns/YYYY-MM.json` (Previous Runs API, one file per month, the same variables as
  forecast one and two days before each valid hour).

Tables: `bronze_ieso_demand` (one row per CSV data row), `bronze_openmeteo_hourly` /
`bronze_openmeteo_forecast` (one row per city and hour) and `bronze_openmeteo_prevruns` (one row
per city, hour and lead in days). Every row keeps `source_file`,
`ingested_at` and `run_date` so a silver row can be traced to the file it came from.
"""

from __future__ import annotations

from datetime import date, datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from gridpulse.config import VARIABLES
from gridpulse.openmeteo import PREVIOUS_DAYS

# The data columns of PUB_Demand. Junk lines start with a backslash and are skipped by `comment`.
IESO_SCHEMA = T.StructType(
    [
        T.StructField("Date", T.StringType()),
        T.StructField("Hour", T.IntegerType()),
        T.StructField("Market Demand", T.DoubleType()),
        T.StructField("Ontario Demand", T.DoubleType()),
    ]
)
_CREATED_RE = r"Created at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"

OPENMETEO_SCHEMA = T.StructType(
    [
        T.StructField("latitude", T.DoubleType()),
        T.StructField("longitude", T.DoubleType()),
        T.StructField(
            "hourly",
            T.StructType(
                [T.StructField("time", T.ArrayType(T.StringType()))]
                + [T.StructField(v, T.ArrayType(T.DoubleType())) for v in VARIABLES]
            ),
        ),
    ]
)
PREVRUNS_SCHEMA = T.StructType(
    [
        T.StructField("latitude", T.DoubleType()),
        T.StructField("longitude", T.DoubleType()),
        T.StructField(
            "hourly",
            T.StructType(
                [T.StructField("time", T.ArrayType(T.StringType()))]
                + [
                    T.StructField(f"{v}_previous_day{d}", T.ArrayType(T.DoubleType()))
                    for d in PREVIOUS_DAYS
                    for v in VARIABLES
                ]
            ),
        ),
    ]
)
CITY_MATCH_DEG = 0.2  # Open-Meteo snaps coordinates to its grid; cities are > 1 degree apart


def _lineage(df: DataFrame, ingested_at: datetime, run_date: date) -> DataFrame:
    return df.withColumn("ingested_at", F.lit(ingested_at).cast("timestamp")).withColumn(
        "run_date", F.lit(run_date).cast("date")
    )


def read_ieso(
    spark: SparkSession, paths: list[str], ingested_at: datetime, run_date: date
) -> DataFrame:
    """PUB_Demand CSV files -> bronze_ieso_demand rows.

    Columns: local_date, hour_ending, market_demand_mw, ontario_demand_mw, source_file,
    source_year, file_version, file_created_at (UTC), ingested_at, run_date.
    FAILFAST: a row that does not match the schema stops the run instead of becoming nulls.
    """
    rows = (
        spark.read.option("header", True)
        .option("comment", "\\")
        .option("escape", '"')
        .option("mode", "FAILFAST")
        .schema(IESO_SCHEMA)
        .csv(paths)
        .select(
            F.to_date("Date", "yyyy-MM-dd").alias("local_date"),
            F.col("Hour").alias("hour_ending"),
            F.col("Market Demand").alias("market_demand_mw"),
            F.col("Ontario Demand").alias("ontario_demand_mw"),
            F.col("_metadata.file_name").alias("source_file"),
        )
    )
    # "\\Created at 2026-11-06 07:30:00" header line, EST wall time -> UTC instant.
    created = (
        spark.read.text(paths)
        .select(
            F.col("_metadata.file_name").alias("source_file"),
            F.regexp_extract("value", _CREATED_RE, 1).alias("created_est"),
        )
        .where(F.col("created_est") != "")
        .groupBy("source_file")
        .agg(F.max("created_est").alias("created_est"))
        .select(
            "source_file",
            F.to_timestamp(
                F.concat(F.col("created_est"), F.lit("-05:00")), "yyyy-MM-dd HH:mm:ssXXX"
            ).alias("file_created_at"),
        )
    )
    out = (
        rows.join(F.broadcast(created), "source_file", "left")
        .withColumn(
            "source_year", F.regexp_extract("source_file", r"PUB_Demand_(\d{4})", 1).cast("int")
        )
        .withColumn(
            "file_version",
            F.when(
                F.col("source_file").rlike(r"_v\d+\.csv$"),
                F.regexp_extract("source_file", r"_(v\d+)\.csv$", 1),
            ),
        )
    )
    return _lineage(out, ingested_at, run_date).select(
        "local_date",
        "hour_ending",
        "market_demand_mw",
        "ontario_demand_mw",
        "source_file",
        "source_year",
        "file_version",
        "file_created_at",
        "ingested_at",
        "run_date",
    )


def read_openmeteo(
    spark: SparkSession,
    paths: list[str],
    cities: DataFrame,
    ingested_at: datetime,
    run_date: date,
) -> DataFrame:
    """Open-Meteo multi-location JSON files -> one row per (city, hour).

    Each file is a JSON array with one object per city holding parallel hourly arrays. Spark
    reads one row per city object, `arrays_zip` + `explode` turns the arrays into rows, and the
    grid coordinates are matched back to the configured cities (a row that matches no city keeps
    city_key = null and fails the silver quality check). `time` is UTC (`timezone=GMT`).
    """
    raw = (
        spark.read.option("multiLine", True)
        .option("mode", "FAILFAST")
        .schema(OPENMETEO_SCHEMA)
        .json(paths)
        .select(
            F.col("latitude").alias("grid_latitude"),
            F.col("longitude").alias("grid_longitude"),
            "hourly.*",
            F.col("_metadata.file_name").alias("source_file"),
        )
    )
    flat = _explode(raw, dict(zip(VARIABLES, VARIABLES, strict=True)))
    matched = _match_cities(flat, cities)
    return _lineage(matched, ingested_at, run_date).select(
        "valid_time",
        "city_key",
        *VARIABLES,
        "grid_latitude",
        "grid_longitude",
        "source_file",
        "ingested_at",
        "run_date",
    )


def _explode(raw: DataFrame, columns: dict[str, str]) -> DataFrame:
    """Parallel hourly arrays -> one row per hour. `columns` maps output name -> array field."""
    exploded = raw.select(
        "grid_latitude",
        "grid_longitude",
        "source_file",
        F.explode(F.arrays_zip("time", *columns.values())).alias("r"),
    )
    return exploded.select(
        "grid_latitude",
        "grid_longitude",
        "source_file",
        F.to_timestamp(F.concat(F.col("r.time"), F.lit("+00:00")), "yyyy-MM-dd'T'HH:mmXXX").alias(
            "valid_time"
        ),
        *[F.col(f"r.{src}").alias(out) for out, src in columns.items()],
    )


def _match_cities(flat: DataFrame, cities: DataFrame) -> DataFrame:
    c = cities.select(
        "city_key", F.col("latitude").alias("_clat"), F.col("longitude").alias("_clon")
    )
    near = (F.abs(F.col("grid_latitude") - F.col("_clat")) <= CITY_MATCH_DEG) & (
        F.abs(F.col("grid_longitude") - F.col("_clon")) <= CITY_MATCH_DEG
    )
    return flat.join(F.broadcast(c), near, "left").drop("_clat", "_clon")


def read_openmeteo_prevruns(
    spark: SparkSession,
    paths: list[str],
    cities: DataFrame,
    ingested_at: datetime,
    run_date: date,
) -> DataFrame:
    """Previous Runs API monthly JSON files -> one row per (city, hour, lead_days).

    `<variable>_previous_day1` / `_previous_day2` become the plain variable names plus a
    `lead_days` column (1 or 2): the value forecast about 24 / 48 hours before the valid hour.
    Before the API's coverage starts the arrays hold nulls; they stay null here (silver keeps
    only complete Ontario aggregates and the model falls back to the historical weather).
    """
    raw = (
        spark.read.option("multiLine", True)
        .option("mode", "FAILFAST")
        .schema(PREVRUNS_SCHEMA)
        .json(paths)
        .select(
            F.col("latitude").alias("grid_latitude"),
            F.col("longitude").alias("grid_longitude"),
            "hourly.*",
            F.col("_metadata.file_name").alias("source_file"),
        )
    )
    parts = [
        _explode(raw, {v: f"{v}_previous_day{d}" for v in VARIABLES}).withColumn(
            "lead_days", F.lit(d).cast("int")
        )
        for d in PREVIOUS_DAYS
    ]
    flat = parts[0]
    for p in parts[1:]:
        flat = flat.unionByName(p)
    matched = _match_cities(flat, cities)
    return _lineage(matched, ingested_at, run_date).select(
        "valid_time",
        "lead_days",
        "city_key",
        *VARIABLES,
        "grid_latitude",
        "grid_longitude",
        "source_file",
        "ingested_at",
        "run_date",
    )

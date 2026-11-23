"""Silver: validated, typed, deduplicated and enriched tables (medallion layer 2).

- `silver_demand_hourly`: one row per UTC hour. IESO hour-ending in fixed EST becomes
  `target_time` (interval start, UTC). When the same hour comes from several files (a revised
  file next to an older one), the most recently created file wins.
- `silver_weather_city_hourly`: one row per (hour, city), deduplicated.
- `silver_weather_ontario_hourly`: one row per hour, population-weighted Ontario aggregates
  (`<variable>_w`), heating and cooling degree hours, and the five city temperatures.
- `silver_demand_weather_hourly`: demand joined with the Ontario weather of the same hour.
- `silver_weather_forecast_ontario`: same aggregates from the Forecast API files (next days),
  newest issue per hour, used by the daily scoring notebook.
- `silver_weather_prevruns_ontario`: same aggregates per (hour, lead_days) from the Previous Runs
  API (forecast 1 or 2 days before the hour), used by nb_forecast to train on weather of the lead
  the daily forecast really has. An aggregate is null unless all five cities have the value.
- Reference data from Azure SQL: `silver_sites`, `silver_meters`, `silver_customers_pseudo`.
  Customer PII (name, email, phone, street address, postal code) and the raw customer_id do not
  reach silver: a salted SHA-256 `customer_hash` replaces them (DESIGN D18).
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from gridpulse.config import CITIES, VARIABLES
from gridpulse.medallion.common import est_date, he_to_target_time

BASE_TEMP_C = 18.0  # degree-hour base temperature (GridCast, common in North American load work)
PII_COLUMNS = ("full_name", "email", "phone", "street_address", "postal_code", "customer_id")
WEIGHTED = tuple(f"{v}_w" for v in VARIABLES)
CITY_TEMPS = tuple(f"temperature_2m_{c.key}" for c in CITIES)


def demand_hourly(bronze_ieso: DataFrame) -> DataFrame:
    """bronze_ieso_demand -> silver_demand_hourly (valid rows only, newest file per hour)."""
    newest_first = Window.partitionBy("target_time").orderBy(
        F.col("file_created_at").desc_nulls_last(), F.col("source_file").desc()
    )
    return (
        bronze_ieso.where(valid_demand_rows())
        .withColumn("target_time", he_to_target_time())
        .withColumn("_rn", F.row_number().over(newest_first))
        .where(F.col("_rn") == 1)
        .select(
            "target_time",
            F.col("local_date").alias("est_date"),
            "hour_ending",
            "ontario_demand_mw",
            "market_demand_mw",
            "source_file",
            "file_created_at",
        )
    )


def valid_demand_rows():
    return (
        F.col("local_date").isNotNull()
        & F.col("hour_ending").between(1, 24)
        & F.col("ontario_demand_mw").isNotNull()
        & F.col("market_demand_mw").isNotNull()
    )


def weather_city_hourly(bronze_om: DataFrame) -> DataFrame:
    """bronze_openmeteo_hourly -> one row per (valid_time, city_key), newest ingestion wins."""
    newest_first = Window.partitionBy("valid_time", "city_key").orderBy(
        F.col("ingested_at").desc(), F.col("source_file").desc()
    )
    return (
        bronze_om.where(F.col("city_key").isNotNull())
        .withColumn("_rn", F.row_number().over(newest_first))
        .where(F.col("_rn") == 1)
        .select("valid_time", "city_key", *VARIABLES, "source_file")
    )


def weather_ontario(weather_city: DataFrame, cities: DataFrame, keys: tuple[str, ...]) -> DataFrame:
    """Population-weighted aggregates per `keys` (e.g. valid_time). Weights are renormalised over
    the cities present, so one missing city does not bias the aggregate (the DQ check flags it)."""
    w = cities.select("city_key", "population_weight")
    joined = weather_city.join(F.broadcast(w), "city_key")
    aggs = [
        (F.sum(F.col(v) * F.col("population_weight")) / F.sum("population_weight")).alias(f"{v}_w")
        for v in VARIABLES
    ]
    aggs += [
        F.avg("temperature_2m").alias("temperature_2m_mean"),
        F.count("*").alias("n_cities"),
    ]
    aggs += [
        F.max(F.when(F.col("city_key") == c.key, F.col("temperature_2m"))).alias(
            f"temperature_2m_{c.key}"
        )
        for c in CITIES
    ]
    out = joined.groupBy(*keys).agg(*aggs)
    return out.withColumn(
        "hdd_w", F.greatest(F.lit(0.0), F.lit(BASE_TEMP_C) - F.col("temperature_2m_w"))
    ).withColumn("cdd_w", F.greatest(F.lit(0.0), F.col("temperature_2m_w") - F.lit(BASE_TEMP_C)))


def weather_ontario_hourly(weather_city: DataFrame, cities: DataFrame) -> DataFrame:
    return weather_ontario(weather_city, cities, ("valid_time",))


def weather_forecast_ontario(bronze_fc: DataFrame, cities: DataFrame) -> DataFrame:
    """Forecast API files `YYYY-MM-DD.json` -> Ontario aggregates per (valid_time), keeping the
    newest issue for each hour. `issued_on` comes from the file name (the run date)."""
    with_issue = bronze_fc.where(F.col("city_key").isNotNull()).withColumn(
        "issued_on",
        F.to_date(F.regexp_extract("source_file", r"(\d{4}-\d{2}-\d{2})", 1), "yyyy-MM-dd"),
    )
    latest = with_issue.groupBy("valid_time").agg(F.max("issued_on").alias("issued_on"))
    newest = with_issue.join(latest, ["valid_time", "issued_on"])
    return weather_ontario(newest, cities, ("valid_time", "issued_on"))


def weather_prevruns_city(bronze_prev: DataFrame) -> DataFrame:
    """bronze_openmeteo_prevruns -> one row per (valid_time, lead_days, city_key), newest
    ingestion wins (the daily run re-copies the current month)."""
    newest_first = Window.partitionBy("valid_time", "lead_days", "city_key").orderBy(
        F.col("ingested_at").desc(), F.col("source_file").desc()
    )
    return (
        bronze_prev.where(F.col("city_key").isNotNull())
        .withColumn("_rn", F.row_number().over(newest_first))
        .where(F.col("_rn") == 1)
        .select("valid_time", "lead_days", "city_key", *VARIABLES, "source_file")
    )


def weather_prevruns_ontario(prev_city: DataFrame, cities: DataFrame) -> DataFrame:
    """Ontario aggregates per (valid_time, lead_days). Unlike `weather_ontario` (which
    renormalises over the cities present), an aggregate is null unless every configured city has
    the value: before the Previous Runs coverage starts most variables are null, and a partial
    aggregate would be a different quantity. nb_forecast then keeps the historical value."""
    n = len(CITIES)
    w = cities.select("city_key", "population_weight")
    joined = prev_city.join(F.broadcast(w), "city_key")

    def complete(col: str, value):
        return F.when(F.count(col) == n, value)

    aggs = [
        complete(
            v, F.sum(F.col(v) * F.col("population_weight")) / F.sum("population_weight")
        ).alias(f"{v}_w")
        for v in VARIABLES
    ]
    aggs += [
        complete("temperature_2m", F.avg("temperature_2m")).alias("temperature_2m_mean"),
        F.count("*").alias("n_cities"),
    ]
    aggs += [
        F.max(F.when(F.col("city_key") == c.key, F.col("temperature_2m"))).alias(
            f"temperature_2m_{c.key}"
        )
        for c in CITIES
    ]
    out = joined.groupBy("valid_time", "lead_days").agg(*aggs)
    tw = F.col("temperature_2m_w")  # greatest() skips nulls, so guard: no temperature, no HDD
    return out.withColumn(
        "hdd_w", F.when(tw.isNotNull(), F.greatest(F.lit(0.0), F.lit(BASE_TEMP_C) - tw))
    ).withColumn("cdd_w", F.when(tw.isNotNull(), F.greatest(F.lit(0.0), tw - F.lit(BASE_TEMP_C))))


def demand_weather_hourly(demand: DataFrame, weather_ont: DataFrame) -> DataFrame:
    """Demand hours with the Ontario weather of the same UTC hour (left join: a demand hour is
    kept even when weather is not there yet; the DQ step counts those)."""
    wx = weather_ont.withColumnRenamed("valid_time", "target_time").drop("n_cities")
    return demand.join(wx, "target_time", "left").select(
        "target_time",
        "est_date",
        "hour_ending",
        "ontario_demand_mw",
        "market_demand_mw",
        *WEIGHTED,
        "temperature_2m_mean",
        "hdd_w",
        "cdd_w",
        *CITY_TEMPS,
    )


# Reference data (S3, Azure SQL -> pipeline copy -> bronze_sites/meters/customers) ---------------


def sites(bronze_sites: DataFrame) -> DataFrame:
    return bronze_sites.select(
        F.col("site_id").cast("int"),
        F.trim("site_code").alias("site_code"),
        F.trim("site_name").alias("site_name"),
        F.trim("city").alias("city"),
        F.col("latitude").cast("double"),
        F.col("longitude").cast("double"),
        F.col("capacity_kw").cast("int"),
    )


def customer_hash(salt: str, col: str = "customer_id"):
    """Salted SHA-256 of the customer id: stable join key, not reversible without the salt."""
    return F.sha2(F.concat(F.lit(salt), F.lit(":"), F.col(col).cast("string")), 256)


def customers_pseudo(bronze_customers: DataFrame, salt: str) -> DataFrame:
    """Customers without PII: hash, city, segment and the customer-since date."""
    return bronze_customers.select(
        customer_hash(salt).alias("customer_hash"),
        F.trim("city").alias("city"),
        F.lower(F.trim("segment")).alias("segment"),
        F.col("created_at").cast("date").alias("customer_since"),
    )


def meters(bronze_meters: DataFrame, salt: str) -> DataFrame:
    """Meters with customer_id replaced by the same salted hash as silver_customers_pseudo."""
    return bronze_meters.select(
        F.trim("meter_id").alias("meter_id"),
        F.col("site_id").cast("int"),
        customer_hash(salt).alias("customer_hash"),
        F.col("install_date").cast("date"),
        F.upper(F.trim("tariff")).alias("tariff"),
        F.col("rated_kw").cast("int"),
        F.lower(F.trim("status")).alias("status"),
    )


def add_est_date(df: DataFrame, ts: str, name: str = "est_date") -> DataFrame:
    return df.withColumn(name, est_date(ts))

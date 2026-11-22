"""Helpers shared by the layers: time conversions that do not depend on the session time zone."""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from gridpulse.config import CITIES

EST_OFFSET_S = 5 * 3600  # IESO market time is EST = UTC-5 all year (DESIGN D9)


def he_to_target_time(local_date: str = "local_date", hour_ending: str = "hour_ending") -> Column:
    """IESO (EST date, hour-ending 1..24) -> interval start as a UTC instant.

    Pure arithmetic on days since the epoch, so the result does not depend on
    spark.sql.session.timeZone: HE1 of date D -> D 05:00Z, HE24 -> D+1 04:00Z.
    """
    seconds = (
        F.unix_date(F.col(local_date)).cast("long") * 86400
        + (F.col(hour_ending).cast("long") - 1) * 3600
        + EST_OFFSET_S
    )
    return F.timestamp_seconds(seconds)


def est_date(ts: str | Column) -> Column:
    """The EST (market) date that contains a UTC instant."""
    c = F.col(ts) if isinstance(ts, str) else ts
    days = F.floor((F.unix_seconds(c) - EST_OFFSET_S) / 86400).cast("int")
    return F.date_from_unix_date(days)


def cities_frame(spark: SparkSession) -> DataFrame:
    """The 5 weather cities with their renormalised population weights (config.CITIES)."""
    schema = T.StructType(
        [
            T.StructField("city_id", T.IntegerType(), False),
            T.StructField("city_key", T.StringType(), False),
            T.StructField("city_name", T.StringType(), False),
            T.StructField("latitude", T.DoubleType(), False),
            T.StructField("longitude", T.DoubleType(), False),
            T.StructField("population_weight", T.DoubleType(), False),
        ]
    )
    rows = [(c.location_id, c.key, c.name, c.lat, c.lon, c.weight) for c in CITIES]
    return spark.createDataFrame(rows, schema)

"""Gold: business tables for the Power BI semantic model (Direct Lake) and the forecast.

Star schema. Facts at three grains share `date_key` with `gold_dim_date`:
- `gold_demand_hourly`  one row per UTC hour (demand, Ontario weather, on-peak flag)
- `gold_demand_daily`   one row per EST day (energy GWh, peak MW and hour, load factor, HDD/CDD)
- `gold_demand_monthly` one row per month (on-peak/off-peak energy, peak, year-over-year)
Analytical tables:
- `gold_top_peaks`            the top 1 % hours of the whole history with their weather
- `gold_temp_sensitivity`     mean demand per 1 degree C bin of Ontario temperature
- `gold_sensitivity_yearly`   heating and cooling slopes (MW per degree C) per year
- `gold_city_weather_daily`   daily weather per city (the report's city slicer)
Dimensions: `gold_dim_date` (built in pandas, see gridpulse.dims), `gold_dim_city`,
`gold_dim_site`, `gold_dim_meter` (no PII: customer_hash and segment only).
`gold_forecast` and `gold_forecast_eval` are written by nb_forecast and nb_predict.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from gridpulse.dims import ONPEAK_HE
from gridpulse.medallion.common import est_date

TOP_FRACTION = 0.01
HEATING_BELOW_C, COOLING_ABOVE_C = 15.0, 20.0


def date_key(col: str = "est_date"):
    return (F.year(col) * 10000 + F.month(col) * 100 + F.dayofmonth(col)).cast("int")


def demand_hourly(demand_weather: DataFrame, dim_date: DataFrame) -> DataFrame:
    d = dim_date.select("est_date", "is_business_day", "season")
    lo, hi = ONPEAK_HE
    return (
        demand_weather.join(F.broadcast(d), "est_date", "left")
        .withColumn("date_key", date_key())
        .withColumn("hour_est", F.col("hour_ending") - 1)
        .withColumn(
            "is_onpeak",
            F.coalesce(F.col("is_business_day"), F.lit(False))
            & F.col("hour_ending").between(lo, hi),
        )
        .select(
            "target_time",
            "est_date",
            "date_key",
            "hour_ending",
            "hour_est",
            "season",
            F.coalesce(F.col("is_business_day"), F.lit(False)).alias("is_business_day"),
            "is_onpeak",
            "ontario_demand_mw",
            "market_demand_mw",
            F.col("temperature_2m_w").alias("temperature_c"),
            F.col("apparent_temperature_w").alias("apparent_temperature_c"),
            F.col("relative_humidity_2m_w").alias("relative_humidity_pct"),
            F.col("cloud_cover_w").alias("cloud_cover_pct"),
            F.col("shortwave_radiation_w").alias("solar_radiation_wm2"),
            F.col("wind_speed_10m_w").alias("wind_speed_kmh"),
            F.col("hdd_w").alias("heating_degree_c"),
            F.col("cdd_w").alias("cooling_degree_c"),
        )
    )


def demand_daily(hourly: DataFrame) -> DataFrame:
    """Energy in GWh = sum of hourly MW / 1000 (each hour is 1 h of MW). Degree days = mean of
    the hourly degree values over the day."""
    return (
        hourly.groupBy("est_date", "date_key")
        .agg(
            F.count("*").alias("hours"),
            (F.sum("ontario_demand_mw") / 1000).alias("energy_gwh"),
            (F.sum(F.when(F.col("is_onpeak"), F.col("ontario_demand_mw"))) / 1000).alias(
                "onpeak_energy_gwh"
            ),
            F.max("ontario_demand_mw").alias("peak_mw"),
            F.max_by("hour_ending", "ontario_demand_mw").alias("peak_hour_ending"),
            F.min("ontario_demand_mw").alias("min_mw"),
            F.avg("ontario_demand_mw").alias("avg_mw"),
            F.avg("temperature_c").alias("temp_mean_c"),
            F.min("temperature_c").alias("temp_min_c"),
            F.max("temperature_c").alias("temp_max_c"),
            F.avg("heating_degree_c").alias("hdd"),
            F.avg("cooling_degree_c").alias("cdd"),
        )
        .withColumn("load_factor", F.col("avg_mw") / F.col("peak_mw"))
        .withColumn("is_complete_day", F.col("hours") == 24)
    )


def demand_monthly(hourly: DataFrame) -> DataFrame:
    """Monthly energy split into on-peak and off-peak, with year-over-year change. YoY is only
    computed when both months are at least 99 % complete (the newest month is partial)."""
    m = (
        hourly.withColumn("month_start", F.trunc("est_date", "month"))
        .groupBy("month_start")
        .agg(
            F.count("*").alias("hours"),
            (F.sum("ontario_demand_mw") / 1000).alias("energy_gwh"),
            (F.sum(F.when(F.col("is_onpeak"), F.col("ontario_demand_mw"))) / 1000).alias(
                "onpeak_energy_gwh"
            ),
            F.max("ontario_demand_mw").alias("peak_mw"),
            F.avg("ontario_demand_mw").alias("avg_mw"),
            (F.sum("heating_degree_c") / 24).alias("hdd"),
            (F.sum("cooling_degree_c") / 24).alias("cdd"),
        )
        .withColumn("year", F.year("month_start"))
        .withColumn("month", F.month("month_start"))
        .withColumn("date_key", date_key("month_start"))
        .withColumn("offpeak_energy_gwh", F.col("energy_gwh") - F.col("onpeak_energy_gwh"))
        .withColumn("onpeak_share", F.col("onpeak_energy_gwh") / F.col("energy_gwh"))
        .withColumn("expected_hours", F.dayofmonth(F.last_day("month_start")) * 24)
        .withColumn("is_complete_month", F.col("hours") >= 0.99 * F.col("expected_hours"))
    )
    prev = m.select(
        F.add_months("month_start", 12).alias("month_start"),
        F.col("energy_gwh").alias("energy_gwh_prev_year"),
        F.col("is_complete_month").alias("_prev_complete"),
    )
    return (
        m.join(prev, "month_start", "left")
        .withColumn(
            "yoy_energy_pct",
            F.when(
                F.col("is_complete_month") & F.coalesce(F.col("_prev_complete"), F.lit(False)),
                100 * (F.col("energy_gwh") / F.col("energy_gwh_prev_year") - 1),
            ),
        )
        .drop("_prev_complete", "expected_hours")
    )


def top_peaks(hourly: DataFrame, fraction: float = TOP_FRACTION) -> DataFrame:
    """Hours at or above the (1 - fraction) demand quantile. The threshold comes from a
    distributed approximate percentile; only the few hundred selected rows are ranked."""
    threshold = hourly.agg(
        F.percentile_approx("ontario_demand_mw", 1 - fraction, 100_000).alias("p")
    ).first()["p"]
    top = hourly.where(F.col("ontario_demand_mw") >= threshold)
    by_year = Window.partitionBy(F.year("est_date")).orderBy(F.col("ontario_demand_mw").desc())
    overall = Window.orderBy(F.col("ontario_demand_mw").desc())  # a few hundred rows only
    return top.select(
        F.row_number().over(overall).alias("peak_rank"),
        F.row_number().over(by_year).alias("peak_rank_in_year"),
        "target_time",
        "est_date",
        "date_key",
        "hour_ending",
        "season",
        "ontario_demand_mw",
        "temperature_c",
        "apparent_temperature_c",
        "relative_humidity_pct",
        "heating_degree_c",
        "cooling_degree_c",
        F.lit(float(threshold)).alias("threshold_mw"),
    )


def temp_sensitivity(hourly: DataFrame) -> DataFrame:
    """Demand profile against temperature: 1 degree C bins, split by season and business day."""
    return (
        hourly.where(F.col("temperature_c").isNotNull())
        .withColumn("temp_bin_c", F.floor("temperature_c").cast("int"))
        .groupBy("temp_bin_c", "season", "is_business_day")
        .agg(
            F.count("*").alias("hours"),
            F.avg("ontario_demand_mw").alias("avg_demand_mw"),
            F.max("ontario_demand_mw").alias("max_demand_mw"),
            F.percentile_approx("ontario_demand_mw", 0.9, 10_000).alias("p90_demand_mw"),
        )
    )


def sensitivity_yearly(hourly: DataFrame) -> DataFrame:
    """Least-squares slope of demand on temperature, per year, on the heating side
    (T < 15 C, reported as MW per degree colder) and on the cooling side (T > 20 C)."""

    def side(cond, sign: float, prefix: str):
        x, y = F.col("temperature_c"), F.col("ontario_demand_mw")
        sub = hourly.where(cond).groupBy(F.year("est_date").alias("year"))
        return sub.agg(
            (sign * F.covar_samp(x, y) / F.var_samp(x)).alias(f"{prefix}_mw_per_c"),
            F.pow(F.corr(x, y), 2).alias(f"{prefix}_r2"),
            F.count("*").alias(f"{prefix}_hours"),
        )

    heat = side(F.col("temperature_c") < HEATING_BELOW_C, -1.0, "heating")
    cool = side(F.col("temperature_c") > COOLING_ABOVE_C, 1.0, "cooling")
    return heat.join(cool, "year", "full")


def city_weather_daily(weather_city: DataFrame) -> DataFrame:
    base = 18.0
    t = F.col("temperature_2m")
    return (
        weather_city.withColumn("est_date", est_date("valid_time"))
        .groupBy("est_date", "city_key")
        .agg(
            F.count("*").alias("hours"),
            F.avg(t).alias("temp_mean_c"),
            F.min(t).alias("temp_min_c"),
            F.max(t).alias("temp_max_c"),
            F.avg(F.greatest(F.lit(0.0), F.lit(base) - t)).alias("hdd"),
            F.avg(F.greatest(F.lit(0.0), t - F.lit(base))).alias("cdd"),
            F.sum("precipitation").alias("precipitation_mm"),
            F.sum("snowfall").alias("snowfall_cm"),
            F.avg("relative_humidity_2m").alias("relative_humidity_pct"),
        )
        .withColumn("date_key", date_key())
    )


def dim_site(sites: DataFrame, meters: DataFrame) -> DataFrame:
    m = meters.groupBy("site_id").agg(
        F.count("*").alias("meter_count"),
        F.sum("rated_kw").alias("rated_kw_total"),
        F.sum((F.col("status") == "active").cast("int")).alias("active_meters"),
    )
    return sites.join(m, "site_id", "left").fillna(0, ["meter_count", "rated_kw_total",
                                                         "active_meters"])  # fmt: skip


def dim_meter(meters: DataFrame, customers: DataFrame, sites: DataFrame) -> DataFrame:
    c = customers.select("customer_hash", "segment", "customer_since")
    s = sites.select("site_id", "site_code", F.col("city").alias("site_city"))
    return meters.join(c, "customer_hash", "left").join(s, "site_id", "left")

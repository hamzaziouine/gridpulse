# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "{{LAKEHOUSE_ID}}",
# META       "default_lakehouse_name": "lh_gridpulse",
# META       "default_lakehouse_workspace_id": "{{WORKSPACE_ID}}"
# META     },
# META     "environment": {
# META       "environmentId": "{{ENVIRONMENT_ID}}",
# META       "workspaceId": "{{WORKSPACE_ID}}"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # nb_gold: business tables for Power BI
#
# Star schema read by the Direct Lake semantic model `sm_gridpulse`: hourly, daily and monthly
# demand facts sharing `date_key` with `gold_dim_date`, the top 1 % peak hours, demand per
# temperature bin, yearly heating/cooling slopes, daily weather per city, and PII-free site and
# meter dimensions. Every table is recomputed from silver on each run (seconds at this size), so a
# rerun cannot duplicate rows.

# PARAMETERS CELL ********************

run_date = ""  # YYYY-MM-DD, empty = today (UTC); only logged here

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

import glob
import sys
from datetime import UTC, datetime, timedelta

try:
    import gridpulse
except ImportError:
    wheels = sorted(glob.glob("/lakehouse/default/Files/libs/gridpulse-*.whl"))
    if not wheels:
        raise
    sys.path.insert(0, wheels[-1])
    import gridpulse

from pyspark.sql import functions as F

from gridpulse.dims import date_dimension
from gridpulse.lakehouse import FabricStore
from gridpulse.medallion import gold
from gridpulse.medallion.common import cities_frame

spark.conf.set("spark.sql.session.timeZone", "UTC")
try:
    store  # injected by scripts/run_local.py for laptop runs
except NameError:
    store = FabricStore(spark)

RUN_DATE = datetime.strptime(run_date, "%Y-%m-%d").date() if run_date else datetime.now(UTC).date()
print(f"gridpulse {gridpulse.__version__} | run_date {RUN_DATE}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Date dimension: every EST date of the history plus 7 days ahead (room for forecasts).
dw = store.read("silver_demand_weather_hourly").cache()
first, last = dw.agg(F.min("est_date"), F.max("est_date")).first()
dim_date = spark.createDataFrame(date_dimension(first, last + timedelta(days=7)))
# pandas gives int64: cast the keys to int so they match the facts' date_key exactly.
dim_date = (
    dim_date.withColumn("est_date", F.col("est_date").cast("date"))
    .withColumn("month_start", F.col("month_start").cast("date"))
    .withColumn("date_key", F.col("date_key").cast("int"))
    .withColumn("year", F.col("year").cast("int"))
    .withColumn("quarter", F.col("quarter").cast("int"))
    .withColumn("month", F.col("month").cast("int"))
    .withColumn("day_of_month", F.col("day_of_month").cast("int"))
    .withColumn("day_of_week", F.col("day_of_week").cast("int"))
    .withColumn("season_order", F.col("season_order").cast("int"))
)

hourly = gold.demand_hourly(dw, dim_date).cache()
s_sites = store.read("silver_sites")
s_meters = store.read("silver_meters")
s_customers = store.read("silver_customers_pseudo")
wx_city = store.read("silver_weather_city_hourly")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

tables = {
    "gold_dim_date": dim_date,
    "gold_dim_city": cities_frame(spark),
    "gold_dim_site": gold.dim_site(s_sites, s_meters),
    "gold_dim_meter": gold.dim_meter(s_meters, s_customers, s_sites),
    "gold_demand_hourly": hourly,
    "gold_demand_daily": gold.demand_daily(hourly),
    "gold_demand_monthly": gold.demand_monthly(hourly),
    "gold_top_peaks": gold.top_peaks(hourly),
    "gold_temp_sensitivity": gold.temp_sensitivity(hourly),
    "gold_sensitivity_yearly": gold.sensitivity_yearly(hourly),
    # Weather starts 2019-01-01 00:00Z = 2018-12-31 19:00 EST: keep only days in gold_dim_date.
    "gold_city_weather_daily": gold.city_weather_daily(wx_city).where(
        F.col("est_date").between(F.lit(first), F.lit(last + timedelta(days=7)))
    ),
}
for name, df in tables.items():
    print(f"{name}: {store.write(df, name):,} rows")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Spot check shown in the demo: the five highest hours on record and the year's peak day.
display(
    store.read("gold_top_peaks")
    .orderBy("peak_rank")
    .select("peak_rank", "target_time", "ontario_demand_mw", "temperature_c", "season")
    .limit(5)
)

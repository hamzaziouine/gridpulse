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

# # nb_predict: tomorrow's 24 hourly forecasts (last step of pl_daily_ingest)
#
# Loads the newest registered version of `gridpulse_lgbm`, builds the features of tomorrow (EST)
# from silver demand (known up to yesterday) and today's Open-Meteo forecast, and writes 24 rows
# with `split = 'live'` to `gold_forecast`. It also fills `actual_mw` of earlier live rows whose
# demand has arrived since, so the report can track live accuracy day by day. Rerunning for the
# same run_date replaces that day's rows.

# PARAMETERS CELL ********************

run_date = ""  # YYYY-MM-DD, empty = today (UTC); forecasts run_date + 1 day
model_name = "gridpulse_lgbm"
model_version = ""  # empty = newest registered version

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

import lightgbm  # noqa: F401  (load LightGBM's native library before pandas/pyarrow)
import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient
from pyspark.sql import functions as F

from gridpulse import features as fx
from gridpulse import forecast as fc
from gridpulse.lakehouse import FabricStore

spark.conf.set("spark.sql.session.timeZone", "UTC")
try:
    store  # injected by scripts/run_local.py for laptop runs
except NameError:
    store = FabricStore(spark)

RUN_DATE = datetime.strptime(run_date, "%Y-%m-%d").date() if run_date else datetime.now(UTC).date()
TARGET_DAY = RUN_DATE + timedelta(days=1)
print(f"gridpulse {gridpulse.__version__} | issue {RUN_DATE} | target day {TARGET_DAY} (EST)")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Inputs as of the issue time: demand only up to day T-2 (what IESO has published at 08:15 EST),
# weather for every hour (history from silver, tomorrow from today's Forecast API file).
lo = TARGET_DAY - timedelta(days=20)
cutoff = TARGET_DAY - timedelta(days=2)
demand = (
    store.read("silver_demand_hourly")
    .where(F.col("est_date").between(F.lit(lo), F.lit(cutoff)))
    .select("target_time", "est_date", "ontario_demand_mw")
    .toPandas()
)
complete = demand.groupby("est_date")["ontario_demand_mw"].count()
newest_full = max(d for d, n in complete.items() if n >= 23)
if newest_full < cutoff:
    raise RuntimeError(f"demand known only up to {newest_full}; need {cutoff}")
t_lo = datetime(lo.year, lo.month, lo.day, tzinfo=UTC)
t_hi = datetime(TARGET_DAY.year, TARGET_DAY.month, TARGET_DAY.day, tzinfo=UTC) + timedelta(days=2)
weather = (
    store.read("silver_weather_ontario_hourly")
    .where((F.col("valid_time") >= F.lit(t_lo)) & (F.col("valid_time") < F.lit(t_hi)))
    .drop("n_cities")
    .toPandas()
    .rename(columns={"valid_time": "target_time"})
)
weather["target_time"] = pd.to_datetime(weather["target_time"], utc=True)
demand["target_time"] = pd.to_datetime(demand["target_time"], utc=True)
hist = weather.merge(demand.drop(columns=["est_date"]), on="target_time", how="outer")
fcw = None
if store.exists("silver_weather_forecast_ontario"):
    fcw = store.read("silver_weather_forecast_ontario").toPandas()
frame, weather_source = fx.live_frame(hist, fcw, TARGET_DAY)
feats = fx.build_features(frame, target_days=[TARGET_DAY])
print(f"{len(feats)} target hours, weather from {weather_source}, demand known to {newest_full}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Model: the requested version, else the newest registered one.
client = MlflowClient()
if model_version:
    version = str(model_version)
else:
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise RuntimeError(f"no registered versions of {model_name}: run nb_forecast first")
    version = str(max(int(v.version) for v in versions))
mv = client.get_model_version(model_name, version)
booster = mlflow.lightgbm.load_model(f"models:/{model_name}/{version}")
scored = feats[list(fx.META_COLUMNS)].assign(forecast=fc.predict(booster, feats))
new_rows = fc.forecast_rows(scored, "live", version, mv.run_id, weather_source)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Keep earlier live rows (with actuals filled in where known), replace this target day.
SCHEMA = (
    "target_time timestamp, est_date date, hour_ending int, issue_date date, date_key int, "
    "split string, model_name string, model_version string, run_id string, forecast_mw double, "
    "naive168_mw double, actual_mw double, abs_error_mw double, ape_pct double, "
    "weather_source string"
)
COLS = [c.strip().split(" ")[0] for c in SCHEMA.split(",")]
live = new_rows
if store.exists("gold_forecast"):
    old = store.read("gold_forecast").where("split = 'live'").toPandas()
    old = old[old["est_date"] != TARGET_DAY]
    if len(old):
        actuals = (
            store.read("silver_demand_hourly")
            .where(F.col("est_date") >= F.lit(min(old["est_date"])))
            .select("target_time", "ontario_demand_mw")
            .toPandas()
        )
        old["target_time"] = pd.to_datetime(old["target_time"], utc=True)
        actuals["target_time"] = pd.to_datetime(actuals["target_time"], utc=True)
        actuals = actuals.rename(columns={"ontario_demand_mw": "actual_mw"})
        old = old.drop(columns=["actual_mw"]).merge(actuals, on="target_time", how="left")
        old["abs_error_mw"] = (old["forecast_mw"] - old["actual_mw"]).abs()
        old["ape_pct"] = old["abs_error_mw"] / old["actual_mw"] * 100
        live = pd.concat([old[COLS], new_rows[COLS]], ignore_index=True)
n = store.write(spark.createDataFrame(live[COLS], SCHEMA), "gold_forecast",
                replace={"split": ["live"]})  # fmt: skip
print(f"gold_forecast live rows: {n} (model {model_name} v{version})")
shown = ["target_time", "hour_ending", "forecast_mw", "naive168_mw", "actual_mw"]
display(spark.createDataFrame(new_rows[COLS], SCHEMA).select(*shown))

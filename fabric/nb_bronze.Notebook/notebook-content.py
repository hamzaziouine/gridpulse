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

# # nb_bronze: landed files to bronze Delta tables
#
# Reads the raw files that `pl_daily_ingest` copied into `Files/bronze/` and writes them, typed and
# with lineage columns, to `bronze_ieso_demand`, `bronze_openmeteo_hourly` and
# `bronze_openmeteo_forecast`. No business rules here: hour-ending, time zones, revisions and
# quality are handled in `nb_silver`.
#
# A daily run (`full_refresh = False`) re-ingests only the files of yesterday's year/month and
# today's forecast, replacing the rows of those files, so running it twice changes nothing. The
# backfill pipeline passes `full_refresh = True`.

# PARAMETERS CELL ********************

run_date = ""  # YYYY-MM-DD, empty = today (UTC)
full_refresh = False  # True: reload every landed file

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Setup: the gridpulse package comes from the env_gridpulse environment; if the notebook runs
# without it, fall back to the wheel uploaded to Files/libs of the default Lakehouse.
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

from gridpulse.lakehouse import FabricStore, file_names
from gridpulse.medallion import bronze
from gridpulse.medallion.common import cities_frame

spark.conf.set("spark.sql.session.timeZone", "UTC")
try:
    store  # injected by scripts/run_local.py for laptop runs
except NameError:
    store = FabricStore(spark)

RUN_DATE = datetime.strptime(run_date, "%Y-%m-%d").date() if run_date else datetime.now(UTC).date()
FULL = str(full_refresh).lower() in ("true", "1")
DATA_DAY = RUN_DATE - timedelta(days=1)  # the newest day IESO has published by 08:00 EST
INGESTED_AT = datetime.now(UTC)
print(f"gridpulse {gridpulse.__version__} | run_date {RUN_DATE} | full_refresh {FULL}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Which landed files this run loads.
ieso_files = store.list_files("bronze/ieso", "PUB_Demand_*.csv")
om_files = store.list_files("bronze/openmeteo", "*.json")
fc_files = store.list_files("bronze/openmeteo_forecast", "*.json")
if not FULL:
    ieso_files = [f for f in ieso_files if f"PUB_Demand_{DATA_DAY.year}" in f]
    om_files = [f for f in om_files if f.endswith(f"{DATA_DAY:%Y-%m}.json")]
    fc_files = [f for f in fc_files if f.endswith(f"{RUN_DATE.isoformat()}.json")]
print(f"IESO files: {file_names(ieso_files)}")
print(f"Open-Meteo history files: {len(om_files)}, forecast files: {file_names(fc_files)}")
if not ieso_files or not om_files:
    raise FileNotFoundError("nothing landed for this run: check the pipeline copy activities")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# IESO demand CSV -> bronze_ieso_demand
ieso = bronze.read_ieso(spark, ieso_files, INGESTED_AT, RUN_DATE)
n_ieso = store.write(
    ieso, "bronze_ieso_demand", replace=None if FULL else {"source_file": file_names(ieso_files)}
)
print(f"bronze_ieso_demand: {n_ieso:,} rows written")
display(ieso.groupBy("source_file", "file_created_at").count().orderBy("source_file"))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Open-Meteo history JSON -> bronze_openmeteo_hourly, forecast JSON -> bronze_openmeteo_forecast
cities = cities_frame(spark)
om = bronze.read_openmeteo(spark, om_files, cities, INGESTED_AT, RUN_DATE)
n_om = store.write(
    om, "bronze_openmeteo_hourly", replace=None if FULL else {"source_file": file_names(om_files)}
)
print(f"bronze_openmeteo_hourly: {n_om:,} rows written")
if fc_files:
    fc = bronze.read_openmeteo(spark, fc_files, cities, INGESTED_AT, RUN_DATE)
    n_fc = store.write(
        fc,
        "bronze_openmeteo_forecast",
        replace=None if FULL else {"source_file": file_names(fc_files)},
    )
    print(f"bronze_openmeteo_forecast: {n_fc:,} rows written")
else:
    print("no forecast file for this run (backfill or local run)")

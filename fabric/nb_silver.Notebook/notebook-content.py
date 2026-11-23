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

# # nb_silver: clean, conform, join, check
#
# 1. Demand: IESO hour-ending (fixed EST, no daylight saving) becomes `target_time`, the UTC start
#    of the hour; when a revised file and an older one both hold an hour, the newest file wins.
# 2. Weather: one row per city and hour, then population-weighted Ontario aggregates with heating
#    and cooling degree hours (base 18 C), joined to demand on the same UTC hour. The Previous
#    Runs weather (forecast 1 and 2 days ahead) gets the same aggregates per lead, complete hours
#    only, in `silver_weather_prevruns_ontario` (training input of nb_forecast).
# 3. Reference data from Azure SQL: customer PII is replaced by a salted SHA-256 hash (salt read
#    from Key Vault), so no silver or gold table holds a name, email, phone or address.
# 4. Quality gate: every check is written to `silver_dq_results`. If one FAILS, the notebook
#    stops before overwriting silver (the last good silver stays) and the pipeline alert fires.

# PARAMETERS CELL ********************

run_date = ""  # YYYY-MM-DD, empty = today (UTC)
key_vault_url = "https://kv-hz2611-cdda.vault.azure.net/"
salt_secret_name = "customer-hash-salt"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

import glob
import sys
import uuid
from datetime import UTC, datetime

try:
    import gridpulse
except ImportError:
    wheels = sorted(glob.glob("/lakehouse/default/Files/libs/gridpulse-*.whl"))
    if not wheels:
        raise
    sys.path.insert(0, wheels[-1])
    import gridpulse

from gridpulse.lakehouse import FabricStore, get_secret
from gridpulse.medallion import quality, silver
from gridpulse.medallion.common import cities_frame

spark.conf.set("spark.sql.session.timeZone", "UTC")
try:
    store  # injected by scripts/run_local.py for laptop runs
except NameError:
    store = FabricStore(spark)

RUN_DATE = datetime.strptime(run_date, "%Y-%m-%d").date() if run_date else datetime.now(UTC).date()
RUN_ID = str(uuid.uuid4())
SALT = get_secret(key_vault_url, salt_secret_name, env_fallback="GRIDPULSE_HASH_SALT")
print(f"gridpulse {gridpulse.__version__} | run_date {RUN_DATE} | run_id {RUN_ID}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Build the silver frames (lazy), cache the ones the checks and the writes both use.
cities = cities_frame(spark)
b_ieso = store.read("bronze_ieso_demand").cache()
b_om = store.read("bronze_openmeteo_hourly")

demand = silver.demand_hourly(b_ieso).cache()
wx_city = silver.weather_city_hourly(b_om).cache()
wx_ont = silver.weather_ontario_hourly(wx_city, cities).cache()
demand_wx = silver.demand_weather_hourly(demand, wx_ont).cache()

b_sites = store.read("bronze_sites")
b_meters = store.read("bronze_meters")
b_customers = store.read("bronze_customers")
s_sites = silver.sites(b_sites)
s_customers = silver.customers_pseudo(b_customers, SALT)
s_meters = silver.meters(b_meters, SALT)

fc = None
if store.exists("bronze_openmeteo_forecast"):
    fc = silver.weather_forecast_ontario(store.read("bronze_openmeteo_forecast"), cities)

# Previous Runs weather (training input of nb_forecast), when the source has landed.
b_prev = prev_city = prev_ont = None
if store.exists("bronze_openmeteo_prevruns"):
    b_prev = store.read("bronze_openmeteo_prevruns")
    prev_city = silver.weather_prevruns_city(b_prev).cache()
    prev_ont = silver.weather_prevruns_ontario(prev_city, cities).cache()

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Quality gate
results = (
    quality.check_bronze_ieso(b_ieso)
    + quality.check_demand(b_ieso, demand, RUN_DATE)
    + quality.check_weather(b_om, wx_city)
    + quality.check_join(demand_wx)
    + quality.check_reference(s_sites, b_meters, b_customers, s_customers, s_meters)
)
if prev_ont is not None:
    results += quality.check_prevruns(b_prev, prev_city, prev_ont, RUN_DATE)
dq = quality.results_frame(spark, results, RUN_ID, RUN_DATE, datetime.now(UTC))
store.write(dq, "silver_dq_results", replace={"run_date": [RUN_DATE]})
display(dq.select("table_name", "check_name", "status", "observed", "expected", "details"))
failed = quality.failures(results)
if failed:
    raise RuntimeError(
        f"{len(failed)} data-quality check(s) failed, silver not updated: "
        + "; ".join(f"{r.table_name}.{r.check_name} observed={r.observed}" for r in failed)
    )

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Checks passed: overwrite the silver tables (full recompute from bronze, idempotent).
written = {
    "silver_demand_hourly": store.write(demand, "silver_demand_hourly"),
    "silver_weather_city_hourly": store.write(wx_city, "silver_weather_city_hourly"),
    "silver_weather_ontario_hourly": store.write(wx_ont, "silver_weather_ontario_hourly"),
    "silver_demand_weather_hourly": store.write(demand_wx, "silver_demand_weather_hourly"),
    "silver_sites": store.write(s_sites, "silver_sites"),
    "silver_meters": store.write(s_meters, "silver_meters"),
    "silver_customers_pseudo": store.write(s_customers, "silver_customers_pseudo"),
}
if fc is not None:
    written["silver_weather_forecast_ontario"] = store.write(fc, "silver_weather_forecast_ontario")
if prev_ont is not None:
    written["silver_weather_prevruns_ontario"] = store.write(
        prev_ont, "silver_weather_prevruns_ontario"
    )
for name, n in written.items():
    print(f"{name}: {n:,} rows")

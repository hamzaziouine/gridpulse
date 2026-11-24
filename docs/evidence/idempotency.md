# Idempotency: two runs of `pl_daily_ingest` for the same date (2026-11-23) and the first scheduled run (2026-11-24)

Success criterion 1 of the proposal: the pipeline runs end to end twice with no duplicate rows. This file holds the evidence from Fabric. Sections 1 to 4 ran in `ws_gridpulse` on 2026-11-23, signed in as Hamza; section 5 is the first scheduled run, on 2026-11-24.

## 1. Runs

| Run | Pipeline | Job instance id (first 8 characters) | Start (UTC) | End (UTC) | Parameters | Status |
|---|---|---|---|---|---|---|
| backfill | `pl_backfill` | `e95b3701` | 2026-11-23 20:41:32 | 2026-11-23 21:45:06 | defaults (2019-01 to 2026-11) | Completed |
| run 1 | `pl_daily_ingest` | `55454d4a` | 2026-11-23 22:13:07 | 2026-11-23 22:36:52 | `run_date = 2026-11-23` | Completed |
| run 2 | `pl_daily_ingest` | `2e39a2de` | 2026-11-23 22:38:42 | 2026-11-23 23:03:16 | `run_date = 2026-11-23` | Completed |

Both daily runs were started by hand with `fab job start ws_gridpulse.Workspace/pl_daily_ingest.DataPipeline -P run_date:string=2026-11-23`. The run date was pinned so that both runs load exactly the same source files. Start and end times come from `fab job run-list`.

## 2. Row counts after each run

Counts were read from the Delta transaction logs of `lh_gridpulse` through the OneLake DFS endpoint (sum of `numRecords` over the files that are live after the last commit). "Commits" is the number of entries in `_delta_log`.

| Table | Rows after run 1 | Rows after run 2 | Commits after run 1 | Commits after run 2 |
|---|---|---|---|---|
| `bronze_customers` | 50 | 50 | 2 | 2 |
| `bronze_ieso_demand` | 69,192 | 69,192 | 2 | 3 |
| `bronze_meters` | 50 | 50 | 2 | 2 |
| `bronze_openmeteo_forecast` | 360 | 360 | 1 | 2 |
| `bronze_openmeteo_hourly` | 345,960 | 345,960 | 2 | 3 |
| `bronze_openmeteo_prevruns` | 253,680 | 253,680 | 2 | 3 |
| `bronze_sites` | 10 | 10 | 2 | 2 |
| `silver_customers_pseudo` | 50 | 50 | 2 | 3 |
| `silver_demand_hourly` | 69,192 | 69,192 | 2 | 3 |
| `silver_demand_weather_hourly` | 69,192 | 69,192 | 2 | 3 |
| `silver_dq_results` | 21 | 21 | 2 | 3 |
| `silver_meters` | 50 | 50 | 2 | 3 |
| `silver_sites` | 10 | 10 | 2 | 3 |
| `silver_weather_city_hourly` | 345,960 | 345,960 | 2 | 3 |
| `silver_weather_forecast_ontario` | 72 | 72 | 1 | 2 |
| `silver_weather_ontario_hourly` | 69,192 | 69,192 | 2 | 3 |
| `silver_weather_prevruns_ontario` | 50,736 | 50,736 | 2 | 3 |
| `gold_city_weather_daily` | 14,415 | 14,415 | 2 | 3 |
| `gold_demand_daily` | 2,884 | 2,884 | 2 | 3 |
| `gold_demand_hourly` | 69,192 | 69,192 | 2 | 3 |
| `gold_demand_monthly` | 95 | 95 | 2 | 3 |
| `gold_dim_city` | 5 | 5 | 2 | 3 |
| `gold_dim_date` | 2,891 | 2,891 | 2 | 3 |
| `gold_dim_meter` | 50 | 50 | 2 | 3 |
| `gold_dim_site` | 10 | 10 | 2 | 3 |
| `gold_forecast` | 24,420 | 24,420 | 2 | 3 |
| `gold_forecast_eval` | 68 | 68 | 1 | 1 |
| `gold_sensitivity_yearly` | 8 | 8 | 2 | 3 |
| `gold_temp_sensitivity` | 315 | 315 | 2 | 3 |
| `gold_top_peaks` | 693 | 693 | 2 | 3 |

Landed files after both runs: `Files/bronze/ieso` 8, `Files/bronze/openmeteo` 95, `Files/bronze/openmeteo_prevruns` 35, the same after run 1 and run 2.

Result: every row count is identical after run 1 and run 2. The commit count grew by one on every table the daily run rewrites, so run 2 really wrote again; it replaced rows instead of adding them. `gold_forecast_eval` is written only by `nb_forecast` (backfill), not by the daily run, so it kept its single commit.

The three `bronze_` reference tables (`bronze_sites`, `bronze_meters`, `bronze_customers`) show 2 commits after both runs for another reason: the copy activity with table action Overwrite recreates the table, log included. After run 2, `_delta_log` of `bronze_sites` holds commits 0 and 1, both written at 22:39:50 to 22:39:51 UTC, inside run 2 (checked on the OneLake file timestamps; `bronze_customers` the same at 22:39:55 to 22:39:57).

## 3. The `gold_forecast` Delta log

`gold_forecast` holds the backtest and holdout rows written by `nb_forecast` and the `live` rows written by `nb_predict`. Its log after run 2:

| Commit | Time (UTC) | Written by | Operation | Predicate | Rows written |
|---|---|---|---|---|---|
| 0 | 2026-11-23 21:44:33 | `nb_forecast` (backfill) | CREATE OR REPLACE TABLE AS SELECT | none | 24,396 |
| 1 | 2026-11-23 22:36:38 | `nb_predict` (run 1) | WRITE, mode Overwrite | `split IN ('live')` | 24 |
| 2 | 2026-11-23 23:02:57 | `nb_predict` (run 2) | WRITE, mode Overwrite | `split IN ('live')` | 24 |

Commits 1 and 2 use Delta `replaceWhere` on the `live` split, so the second run replaced the 24 live rows of the first one. After run 2 the table has 16,577 backtest rows, 7,819 holdout rows and 24 live rows, 24,420 in total. The live rows are the forecast for EST day 2026-11-24, hour-ending 1 to 24, between 14,430 and 19,118 MW (mean 16,694 MW), model `gridpulse_lgbm` version 1, weather from the Forecast API.

## 4. Caveat: this was a same-day test

Both runs used the same `run_date` and the same source files, so they prove that a rerun does not duplicate rows. They do not prove that consecutive days add the right rows: a new day changes the IESO year file, the Open-Meteo month and the forecast window.

The real multi-day test is the first scheduled run, 2026-11-24 at 13:15 UTC (`run_date` 2026-11-24). Expected after it: `gold_forecast` 24,444 rows, 48 of them `live` (the 24 rows already written for 2026-11-24 plus 24 new rows for 2026-11-25). Fewer than 48 live rows would mean the `live` overwrite drops earlier days.

Status: **passed**. Section 5 has the numbers.

## 5. First scheduled run, 2026-11-24

The schedule started `pl_daily_ingest` on its own: job instance `c5e1df2b` (first 8 characters of its id), invoke type Scheduled, started 13:15:04 UTC, finished 13:40:09 UTC, status Completed, no failure reason. Row counts were read the same way as in section 2, from the Delta logs, after the run:

| Table | After run 2 (11-23) | After the 11-24 run | Change |
|---|---|---|---|
| `bronze_ieso_demand` | 69,192 | 69,216 | +24 |
| `bronze_openmeteo_hourly` | 345,960 | 346,080 | +120 (24 h x 5 cities) |
| `bronze_openmeteo_prevruns` | 253,680 | 253,920 | +240 |
| `bronze_openmeteo_forecast` | 360 | 720 | +360 |
| `silver_demand_hourly` | 69,192 | 69,216 | +24 |
| `silver_demand_weather_hourly` | 69,192 | 69,216 | +24 |
| `silver_weather_ontario_hourly` | 69,192 | 69,216 | +24 |
| `silver_weather_city_hourly` | 345,960 | 346,080 | +120 |
| `silver_weather_prevruns_ontario` | 50,736 | 50,784 | +48 |
| `silver_weather_forecast_ontario` | 72 | 96 | +24 |
| `silver_dq_results` | 21 | 42 | +21 (one new `run_date`) |
| `gold_demand_hourly` | 69,192 | 69,216 | +24 |
| `gold_demand_daily` | 2,884 | 2,885 | +1 |
| `gold_dim_date` | 2,891 | 2,892 | +1 |
| `gold_city_weather_daily` | 14,415 | 14,420 | +5 |
| `gold_top_peaks` | 693 | 695 | +2 |
| `gold_forecast` | 24,420 | 24,444 | +24 |

Every other table kept its count (reference tables 10 / 50 / 50, `gold_demand_monthly` 95, `gold_sensitivity_yearly` 8, `gold_temp_sensitivity` 315, dims, `gold_forecast_eval` 68). Landed files did not change in number (`ieso` 8, `openmeteo` 95, `openmeteo_prevruns` 35) because the run rewrote the current files in place: `PUB_Demand_2026.csv`, `openmeteo/2026-11.json` and `openmeteo_prevruns/2026-11.json` all show a last-modified time of 13:15 UTC on 11-24, the older files still show 11-23. The forecast copy writes one file per issue day instead: `Files/bronze/openmeteo_forecast` now holds `2026-11-23.json` and `2026-11-24.json`.

`gold_forecast` now holds 16,577 backtest, 7,819 holdout and **48 live** rows: 24 issued on 2026-11-23 for EST day 2026-11-24 and 24 issued on 2026-11-24 for EST day 2026-11-25. Its commit 3 (13:39:56 UTC) is again a `replaceWhere` on `split IN ('live')`, which deleted the 24 old live rows and wrote 48, so the earlier day was kept and nothing was doubled. At run time one hour of the forecast for EST day 2026-11-24 (issued on 2026-11-23) already had an actual value; one hour says nothing about accuracy yet.

`silver_dq_results` commit 3 is a `replaceWhere` on `run_date IN (DATE '2026-11-24')`: 21 new rows, 0 deleted, so the 11-23 rows stay as history. The 11-24 checks gave 18 PASS, 3 WARN, 0 FAIL, the same three warnings as on 11-23 (the known IESO gap at 2025-05-01 05:00Z, which shows up in `hourly_gaps` and `hours_per_day_24`, and 6 recent demand hours without weather yet, none older than 72 h).

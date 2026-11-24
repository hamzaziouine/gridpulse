# Fabric batch path: deployment and run evidence (2026-11-23)

What exists in Fabric and what the batch runs did, as read back on 2026-11-23 with `fab` and the Fabric REST API, signed in as Hamza. The scheduled run of 2026-11-24 was read back on 2026-11-24. Idempotency counts are in `docs/evidence/idempotency.md`. Job and run ids are shortened to their first 8 characters.

## 1. Capacity

The workspace runs on an FTL4 Fabric trial capacity in Germany West Central, created on 2026-10-19. It belongs to a classmate outside the team, who left contributor permissions open on it. It is not Nacir's: his own trial was not visible from any of our accounts on 2026-11-23 (see `docs/MANUAL_STEPS.md`, step 0). `[TO CONFIRM: the capacity owner's agreement to host ws_gridpulse]`

A trial lasts 60 days, so this one should end around 2026-12-18 (estimate from the creation date, not read from the API). The daily schedule stops on 2026-12-17 for that reason. Moving to another capacity means reassigning `ws_gridpulse` and running `pl_backfill` again.

Etiquette on a shared capacity: one backfill, one scheduled run a day, no loops.

## 2. Items in `ws_gridpulse`

`fab ls ws_gridpulse.Workspace` on 2026-11-23:

| Item | Type | Created by | Note |
|---|---|---|---|
| `lh_gridpulse` | Lakehouse (+ SQL analytics endpoint) | `deploy_fabric.ps1` | 30 Delta tables after the runs |
| `env_gridpulse` | Environment | `deploy_fabric.ps1` | Runtime 1.3, starter pool, driver and executor 4 cores / 28 GB, 1 to 2 executors; wheel `gridpulse-0.2.0` + `holidays==0.108`; published |
| `nb_bronze`, `nb_silver`, `nb_gold`, `nb_forecast`, `nb_predict` | Notebooks | `deploy_fabric.ps1` | default Lakehouse `lh_gridpulse`, environment `env_gridpulse` |
| `pl_backfill`, `pl_daily_ingest` | Data pipelines | `deploy_fabric.ps1` | no failure mail yet (no Outlook connection) |
| `eh_gridpulse` | Eventhouse + KQL database | `deploy_fabric.ps1` + `run_kql.py` | table `meter_readings` and mapping `meter_readings_json` exist; **0 rows** |
| `es_meters` | Eventstream | `deploy_fabric.ps1` | empty: no source, no destination yet (browser step) |
| `exp_gridpulse_forecast` | ML experiment | `nb_forecast` | |
| `gridpulse_lgbm` | ML model | `nb_forecast` | version 1 used by `nb_predict` |

Fabric autologging also created an experiment named `nb_forecast` during the backfill, holding the backtest fits. It was deleted on 2026-11-24 and autologging is now off in `nb_forecast`, so a new backfill does not recreate it.

Connections (tenant level, outside the workspace): `con_ieso_http`, `con_openmeteo_hist`, `con_openmeteo_fc`, `con_openmeteo_prev` (HTTP, anonymous) and `con_sql_gridpulse` (SQL, basic auth with the `gpadmin` password from Key Vault, encrypted). `con_outlook_alerts` does not exist yet.

Not built yet: the KQL queryset, `rtd_gridpulse`, `act_abnormal_demand`, `sm_gridpulse`, `rpt_gridpulse`. The real-time path is unverified: the simulator has never sent an event to `es_meters`, so no KQL query has run on stream data.

## 3. Schedule

One schedule on `pl_daily_ingest` (`fab job run-list ... --schedule`): enabled, daily at 13:15, time zone UTC, from 2026-11-24 00:00 to 2026-12-17 00:00. It fired for the first time on 2026-11-24 at 13:15:04 UTC (job instance `c5e1df2b`, Completed at 13:40:09 UTC; counts in `docs/evidence/idempotency.md`, section 5). With no failure mail, a failed scheduled run is visible only in the Monitor hub.

## 4. Backfill run (`pl_backfill`)

Job `e95b3701`, 2026-11-23 20:41:32 to 21:45:06 UTC (63.5 min), Completed, every activity Succeeded with no retry.

| Activity | Start (UTC) | End (UTC) | Duration |
|---|---|---|---|
| `fe_ieso_years` (8 copies) | 20:41:43 | 20:42:26 | 42 s |
| `fe_sql_reference` (3 copies) | 20:41:43 | 20:43:06 | 82 s |
| `fe_prevruns_months` (35 copies, sequential) | 20:41:43 | 20:52:02 | 618 s |
| `fe_openmeteo_months` (95 copies, sequential) | 20:41:43 | 21:10:12 | 1,708 s (28.5 min) |
| `nb_bronze` (full refresh) | | | 258 s |
| `nb_silver` | | | 368 s |
| `nb_gold` | | | 338 s |
| `nb_forecast` | | | 1,121 s |

The four ForEach loops run in parallel, so the copy phase took 28.5 min, set by the 95 sequential Open-Meteo months. Durations are the activity run durations returned by the pipeline's `queryactivityruns` API (for notebooks, Spark session start is included). The backfill notebook rows show durations only; their start and end times were not recorded.

## 5. Daily run (`pl_daily_ingest`, run 2)

Job `2e39a2de`, `run_date` 2026-11-23, 22:38:42 to 23:03:16 UTC (about 25 min), Completed, 15 of 15 activity runs Succeeded.

| Activity | Start (UTC) | End (UTC) | Duration |
|---|---|---|---|
| `cp_ieso_demand` | 22:38:51 | 22:39:11 | 20 s |
| `cp_openmeteo_history` | 22:38:51 | 22:39:08 | 16 s |
| `cp_openmeteo_forecast` | 22:38:51 | 22:39:07 | 15 s |
| `cp_openmeteo_prevruns` | 22:38:51 | 22:39:05 | 14 s |
| `fe_sql_reference` (3 copies) | 22:38:51 | 22:40:14 | 82 s |
| `nb_bronze` | 22:40:14 | 22:45:00 | 286 s |
| `nb_silver` | 22:45:01 | 22:53:10 | 489 s |
| `nb_gold` | 22:53:12 | 22:58:50 | 338 s |
| `nb_predict` | 22:58:51 | 23:03:14 | 263 s |

Run 1 (`55454d4a`) took about 24 min. Most of a daily run is notebook time; the copies take under 1.5 min.

## 6. Data quality in Fabric

`silver_dq_results` after run 2 (run id `c33c7145`): 21 checks, **18 PASS, 3 WARN, 0 FAIL**. The backfill and run 1 gave the same 21 results.

| Table | Check | Status | Observed | Details |
|---|---|---|---|---|
| `silver_demand_hourly` | `hourly_gaps` | WARN | 1 | 2025-05-01 05:00Z, the hour IESO never published |
| `silver_demand_hourly` | `hours_per_day_24` | WARN | 1 | 2025-05-01 has 23 hours (same gap) |
| `silver_demand_weather_hourly` | `weather_coverage` | WARN | 6 | 6 newest demand hours without weather yet, none older than 72 h |

The 18 other checks passed, among them `pii_absent` on `silver_customers_pseudo`, `fk_site` and `fk_customer` on `silver_meters`, and the 4 Previous Runs checks (coverage: day 1 has 17,190 complete hours from 2024-12-06 18Z to 2026-11-22 23Z, day 2 has 17,166). `freshness_days` saw newest EST date 2026-11-23.

`nb_silver` read `customer-hash-salt` from Key Vault in Fabric in a pipeline run started by Hamza (`silver_customers_pseudo` has 50 rows). The scheduled run of 2026-11-24 did the same: `silver_customers_pseudo` commit 3 was written at 13:28:26 UTC inside that run, 50 rows.

## 7. Model metrics from the cloud run

Computed from the `holdout` and `backtest` rows of `gold_forecast` written by `nb_forecast` in the backfill (data to 2026-11-22). These are cloud figures. The local figures in `docs/evidence/model_metrics.md` come from a different run with data to 2026-11-06 and are not comparable hour for hour.

| Evaluation | Target hours (UTC) | Hours | LightGBM MAPE | Seasonal naive MAPE |
|---|---|---|---|---|
| Holdout, model frozen after 2025 | 2026-01-01 05:00 to 2026-11-22 23:00 | 7,819 | 2.815 % | 6.724 % |
| Backtest, retrained monthly | 2025-01-01 05:00 to 2026-11-22 23:00 | 16,577 | 2.546 % | 6.895 % |

Skill against the naive baseline (1 - MAPE model / MAPE naive): 58.1 % on the holdout, 63.1 % on the backtest, above the 30 % of success criterion 6. Same caveats as the local run: the boosting round count was chosen on 2025 and reused in the 2025 backtest folds, and the lead-matched training setting was chosen on the 2026 holdout (report section 9.4). Only the `live` rows will give an unbiased figure.

`gold_forecast_eval` (68 rows, monthly errors) is written by `nb_forecast` only. The daily run does not refresh it.

## 8. Not verified yet

- Eventstream, Eventhouse ingestion and KQL on stream data (no event sent yet).
- Failure mail (no Outlook connection).
- Power BI semantic model and report (not built).
- Screenshots of the Monitor hub. `[TO DECIDE: who takes them and when]`

# GridPulse demo script (10 to 15 minutes)

Follows the 7 steps of the brief, section 7. Target length 13 minutes, which leaves 2 minutes of slack inside the 15. Every member drives at least one step, as the rubric's "balanced group participation" asks.

Status 2026-11-22: nothing is deployed in Fabric yet, so every timing and expected screen below is a plan. Times marked `[TODO]` get measured in rehearsal 1 (PLAN T11.4).

| Step | Brief item | Owner | Time | Clock |
|---|---|---|---|---|
| 1 | Source data and its structure | shared: Omar opens, Hamza (S1, S2), Nacir (S3) | 1:45 | 0:00 to 1:45 |
| 2 | Trigger the batch ingestion | Hamza | 1:45 | 1:45 to 3:30 |
| 3 | Spark notebook and curated Delta output | Hamza | 2:00 | 3:30 to 5:30 |
| 4 | Live events and KQL queries | Nacir | 2:45 | 5:30 to 8:15 |
| 5 | Power BI, two business questions | Omar | 2:00 | 8:15 to 10:15 |
| 6 | One security control, one trade-off | Hamza (member 4 if one joins) | 1:30 | 10:15 to 11:45 |
| 7 | Limitations, cost, next steps | Omar | 1:15 | 11:45 to 13:00 |

Persona rule during the demo: each member works in their own browser profile signed in with their own account. Omar (Analyst) has no SQL user and no Key Vault access, so he never shows the SQL tables; Nacir (Admin) does. On 2026-11-23 the SQL server has no Entra admin (`docs/evidence/rbac.md`), so nobody can sign in to it with an Entra account yet. `[TO DECIDE: set Nacir as SQL Entra admin before the demo, or have him use the gpadmin login with the password from Key Vault]`

## Pre-demo checklist

The day before:

- [ ] Rehearsal done; fallback video recorded (PLAN T11.2) and copied to the laptop, so it plays without network. One screenshot per step in `docs/evidence/demo/`.
- [ ] Nacir's trial capacity is active and not paused; `ws_gridpulse` opens for all three accounts.
- [ ] Omar's workspace role is back to Viewer (he was Contributor while building the report) and his Power BI trial is still active.
- [ ] `powershell -File infra\azure\policy_assignments.ps1 -Test` run once: the output must say "DENIED by policy, as expected". Saved in `docs/evidence/policy.md` as the fallback.

60 minutes before:

- [ ] Laptop on the charger. Phone hotspot tested. The simulator talks AMQP over TLS (port 5671); if the campus network blocks that port, switch to the hotspot, because the simulator has no WebSocket option yet.
- [ ] Three browser profiles signed in at `app.fabric.microsoft.com`: Hamza, Nacir, Omar. Azure portal open in Nacir's profile.
- [ ] Terminal in `C:\Users\ultra pc\dev\gridpulse`: `az account show --query user.name` prints Hamza's UIR account; `fab auth status` shows Hamza.

45 minutes before:

- [ ] Pipeline. The daily schedule fires at 13:15 UTC, which is 14:15 in Morocco (UTC+1), so it would start in the middle of a 14:00 class slot. Run `pl_daily_ingest` by hand now, wait until it is green in the Monitor hub, then switch the schedule off for the rest of the slot and back on after the demo. A full daily run took about 24 and 25 minutes on 2026-11-23 (`docs/evidence/fabric_batch.md`), so start it at least 30 minutes before.
- [ ] Open the `nb_silver` and `nb_gold` run snapshots of that run (Monitor hub > the run > activity > notebook snapshot) in tabs.

20 minutes before (at least 15 minutes before step 4):

- [ ] `realtime\anomaly.json` does not exist: `Test-Path realtime\anomaly.json` prints `False`. A leftover file would fire the anomaly at start-up.
- [ ] Start the simulator. It reads the Eventstream connection string from Key Vault with the signed-in `az` identity:

```powershell
cd "C:\Users\ultra pc\dev\gridpulse"
uv run python realtime/simulator.py --kv-url https://kv-hz2611-cdda.vault.azure.net --kv-secret es-meters-conn --rate 10
```

- [ ] stderr shows `sent 50`, `sent 100`, and so on. In `kq_gridpulse`, `meter_readings | where ts > ago(1m) | count` returns about 600 (10 events/s).
- [ ] Q2 returns 0 rows. Q2 only flags a site once it has at least 10 complete baseline minutes (`n >= 10` in `q2_anomaly.kql`), so a simulator started only 10 minutes before is the bare minimum; 15 minutes leaves margin.

10 minutes before, tabs open in this order:

1. `docs/architecture.png`
2. `lh_gridpulse` > Files > `bronze/ieso` and `bronze/openmeteo` (Hamza)
3. Azure portal > `sqldb-hz2611-gridpulse` > Query editor, plus Data Discovery and Classification (Nacir)
4. `pl_daily_ingest` and the Monitor hub (Hamza)
5. `nb_silver` and `nb_gold` snapshots, and the `lh_gridpulse` SQL analytics endpoint with the two saved queries of step 3 (Hamza)
6. `kq_gridpulse` and `rtd_gridpulse` (Nacir)
7. `rpt_gridpulse` (Omar's profile)
8. terminal for the policy test (Hamza)
9. Outlook web inbox, for the Activator mail
10. local folder with the fallback video and screenshots

Last checks: notifications off (Windows focus mode), browser zoom 125 %. Nobody starts an interactive Spark session during step 4: the trial capacity has 4 CU, and the live path should not compete with a Spark job (PLAN risk 2).

## Step 1. Source data and structure (shared, 1:45)

Omar, 20 s. "Ontario's grid operator needs to know when and why demand peaks, and which sites behave abnormally right now. We built one governed platform for history, live events and a day-ahead forecast." Shows `docs/architecture.png`: four sources on the left, batch path in the middle, real-time path on top, security band at the bottom.

Hamza, 50 s. In `lh_gridpulse` > Files:

- `bronze/ieso/PUB_Demand_2026.csv`: one file per year, header lines starting with a backslash, columns `Date, Hour, Market Demand, Ontario Demand`. Hour is hour-ending 1 to 24 in fixed EST all year (no daylight saving), which we convert to UTC.
- `bronze/openmeteo/2026-10.json`: one object per city with parallel hourly arrays; 5 cities, 9 variables. It is the Historical Forecast API: weather as it was forecast at the time, not as observed.

Nacir, 35 s. In the portal Query editor (needs the SQL Entra admin of the persona rule above, not set on 2026-11-23):

```sql
SELECT TOP 3 * FROM dbo.meters;
SELECT TOP 3 customer_id, city, segment FROM dbo.customers;
SELECT schema_name(o.schema_id) AS s, o.name AS t, c.name AS col, sc.label, sc.information_type
FROM sys.sensitivity_classifications sc
JOIN sys.objects o ON o.object_id = sc.major_id
JOIN sys.columns c ON c.object_id = sc.major_id AND c.column_id = sc.minor_id;
```

The audience sees 10 sites, 50 meters and 50 customers in a relational schema with keys, and the 5 PII columns with their classifications. The fourth source, the meter events, appears in step 4.

Fallback: screenshots `docs/evidence/demo/01_*.png`.

## Step 2. Trigger the batch ingestion (Hamza, 1:45)

1. Open `pl_daily_ingest`. Point at the four copy activities (IESO CSV over HTTP, Open-Meteo history and forecast over REST, the three SQL tables), then the notebook chain `nb_bronze`, `nb_silver`, `nb_gold`, `nb_predict`, and the failure branch (Outlook mail, then a Fail activity).
2. Click Run, keep the default `run_date`. CLI equivalent if the UI misbehaves:

```powershell
fab job start ws_gridpulse.Workspace/pl_daily_ingest.DataPipeline
```

3. The copy activities turn green within seconds `[TODO after T3.3: real copy durations]`. Switch to the Monitor hub: the run in progress, and the run of 45 minutes ago, all green, with its duration per activity.
4. One sentence on repeatability: "nb_bronze replaces the rows of the files it re-reads, and silver and gold are recomputed and overwritten, so running the same day twice gives the same row counts." `[TODO after T3.4: docs/evidence/idempotency.md with counts before and after a second run]`
5. Show the schedule: daily at 13:15 UTC, which is 08:15 EST, after IESO publishes the previous day.

Fallback: screenshot of the pipeline canvas and of the Monitor hub with the earlier green run.

## Step 3. Spark notebook and curated Delta output (Hamza, 2:00)

1. Open the `nb_silver` snapshot of the pre-demo run. The `silver_dq_results` display shows 21 checks in Fabric (17 plus 4 on the Previous Runs weather). Cloud runs of 2026-11-23: 18 PASS, 3 WARN, 0 FAIL (the local run of 2026-11-22 had 17 checks: 14 PASS, 3 WARN, 0 FAIL). The 3 WARN are known conditions:
   - `hourly_gaps`: IESO never published 2025-05-01 hour-ending 1 (market renewal go-live);
   - `hours_per_day_24`: the same day therefore has 23 hours;
   - `weather_coverage`: the newest 6 demand hours wait for the next weather file.
   A FAIL would stop `nb_silver` before it overwrites silver, and the pipeline would fail. The failure mail needs `con_outlook_alerts`, which does not exist yet.
2. Open the `nb_gold` snapshot: one line per gold table with its row count, then the five highest hours on record.
3. In the `lh_gridpulse` SQL analytics endpoint, run the two saved queries:

```sql
SELECT TOP 5 peak_rank, target_time, ontario_demand_mw, temperature_c, season
FROM gold_top_peaks ORDER BY peak_rank;

SELECT check_name, status, observed, details
FROM silver_dq_results
WHERE run_date = (SELECT MAX(run_date) FROM silver_dq_results);
```

4. In the Lakehouse explorer, open `gold_demand_daily` > View files: Parquet files plus the `_delta_log` folder, so this is a Delta table.
5. If the run started in step 2 has finished by now (check the Monitor hub), open its `nb_gold` snapshot instead and say so.

Expected from the local run: the top hour is 2026-07-14, hour-ending 17 EST, 25,646 MW, population-weighted temperature about 36 °C. `[TODO after T4.2: same check on the Fabric run]`

Fallback: snapshot screenshots, or the recorded video at `[TODO after T11.2: timestamp]`.

## Step 4. Live events and KQL (Nacir, 2:45)

1. Show the simulator terminal: one JSON reading per meter, 10 events per second. Example event (from a local `--dry-run`): `{"ts": "2026-11-22T19:01:58.037Z", "meter_id": "MTR-0003", "site_id": 3, "kw": 43.535, "voltage": 238.75, "status": "active"}`. The connection string came from Key Vault; it is not on disk.
2. Open `es_meters`: custom endpoint source, Eventhouse destination, live event count.
3. In `kq_gridpulse`, run:

```kql
meter_readings | where ts > ago(1m) | count
```

   then Q1 (`q1_5min_window.kql`, kWh per site in 5-minute tumbling windows) and Q3 (`q3_top5.kql`, top 5 sites over 15 minutes). Optional ingestion delay check:

```kql
meter_readings | where ts > ago(5m) | summarize avg_delay_s = avg(ingestion_time() - ts) / 1s
```

   `[TODO after T6.4: measured delay, target under 10 s]`

4. Inject the anomaly from a second terminal (site 5 at three times its normal load for 5 minutes):

```powershell
Set-Content -Path realtime\anomaly.json -Value '{"site_id": 5, "factor": 3.0, "seconds": 300}' -Encoding ascii
```

   The simulator prints `anomaly armed: ...` and renames the file to `anomaly.done.json`. Use `-Encoding ascii`: with Windows PowerShell's default encodings the file could get a byte-order mark or UTF-16, which the simulator's JSON read rejects.
5. While the minute completes, show `rtd_gridpulse` (Q1 per-site chart, Q2 table, Q3 bar chart). Q2 compares the last complete minute with each site's trailing hour, so the row appears 1 to 2 minutes after the injection.
6. Run Q2 (`q2_anomaly.kql`): one row for `site_id` 5 with `z` far above 3. The same query drives `act_abnormal_demand`; the mail is checked in step 7. `[TODO after T6.6: measured delay between injection and mail]`

Fallback: if no events arrive, switch to the hotspot and restart the simulator; if still nothing, play the video section `[TODO after T11.2: timestamp]` and show the Q1 to Q3 screenshots.

## Step 5. Power BI, two business questions (Omar, 2:00)

Omar opens `rpt_gridpulse` in his own profile, as Viewer. He says the model is Direct Lake on the gold tables, so this morning's pipeline run is already in the report without a refresh.

Question 1: "When do demand peaks happen, and how high are they?" Page Peaks: hour by weekday heatmap, peak load KPI card, top peaks table. Expected answer from the local run: the highest hour was 2026-07-14, hour-ending 17 EST, at 25,646 MW; 659 of the 688 top-1 % hours fall in summer, so peaks are a summer, late-afternoon cooling problem. `[TODO after T7.2: confirm on the Fabric report]`

Question 2: "How strongly does temperature drive demand?" Page Weather sensitivity: demand against temperature, yearly slopes. Expected answer from the local run: on the cooling side demand rises by about 570 to 730 MW per °C above 20 °C depending on the year (2019 to 2026), on the heating side by about 160 to 200 MW per °C below 15 °C. Per degree, a hot day costs the grid three to four times more than a cold one. He uses the year and season slicers once to show the interaction.

If time allows, page Forecast vs actual: model MAPE against seasonal-naive MAPE (local run: holdout 2026 MAPE 2.90 % against 6.84 % for the naive baseline, with weather of the production lead time; quote the Fabric figures once T5.1 has run).

Fallback: the report screenshots, or the downloaded PBIX opened in Power BI Desktop.

## Step 6. One security control and one trade-off (Hamza, or member 4; 1:30)

Control, live (needs Hamza's `az` session; since 2026-11-23 he holds Contributor and Resource Policy Contributor on the RG, but the `-Test` so far ran only under Nacir's session. `[TO CONFIRM: one rehearsal run of the -Test as Hamza]`):

```powershell
powershell -File infra\azure\policy_assignments.ps1 -Test
```

Expected output: the two assignments `require-tag-project` and `require-tag-owner`, then `DENIED by policy, as expected:` and a line with `RequestDisallowedByPolicy`. The storage account was refused; nothing was created. Then one sentence on the personas: "I am the Data Engineer: I can deploy into this resource group but not grant roles. Omar, the Analyst, gets 403 on Key Vault and only sees gold through the semantic model." Both claims are untested on 2026-11-23 (`docs/MANUAL_STEPS.md`, step 7); say them only after the check.

Trade-off: one Lakehouse with `bronze_`, `silver_`, `gold_` prefixes instead of three (DESIGN D6). Gain: one Direct Lake source, a third of the setup, fits the trial. Cost: a workspace role covers every layer, including `bronze_customers` with PII. We compensate by hashing customers in silver and giving the Analyst access through the semantic model only; in production we would put bronze in its own Lakehouse or workspace.

Fallback: `docs/evidence/azure_foundation.md`, section 2 (saved output of the same command).

## Step 7. Limitations, cost, next steps (Omar, 1:15)

- Cost: Fabric trial capacity $0, Azure SQL free offer $0 (it pauses when the free monthly allowance is used up), Key Vault under $0.10 a month; expected total under $2, with a $20 budget alert at 50 % and 100 %. After grading, `cleanup.ps1` deletes the resource group and the workspace is removed (`docs/resource_inventory.md`).
- Limitations: trial capacity of 4 CU, so we keep the event rate at 10 per second; the simulator runs on a laptop; lead-matched weather (Previous Runs) exists only from 2024, so older training years use short-lead weather; measured on 2026, the short-lead setting looked better than it is (2.70 % instead of 3.07 %), and training on lead-matched weather brings it to 2.90 % (naive 6.84 %); the Purview scan is designed, not built; endpoints are public.
- Next steps: private endpoints and a read-only identity for the SQL copy; incremental MERGE instead of full recomputes once data grows; monthly retraining with a drift check; the simulator replaced by a real meter feed.
- Show the Activator mail in the inbox if it has arrived.

## Likely professor questions

1. Why Eventhouse and not the Lakehouse for live data?
   Eventhouse ingests a stream in seconds, indexes it by time, and KQL is built for time windows (`bin(ts, 5m)`); the Real-Time Dashboard and Activator query it directly, and retention is one policy per table (7 days). Writing the stream into the Lakehouse needs Spark Structured Streaming: micro-batch latency, small Delta files to compact, more code. History stays in the Lakehouse; if we needed the live table there too, the KQL database can expose it to OneLake.

2. What if the data volume grows 100 times?
   The batch sources barely grow (one provincial demand series, 5 cities). Growth would come from meters: 5,000 meters at 1,000 events per second. Eventstream is Event Hubs underneath and takes that rate; the Eventhouse and the capacity have to grow (larger F SKU, sized with the Capacity Metrics app), and Q1 and Q2 would move to materialized views so the dashboard does not rescan raw rows. In the Lakehouse we would partition meter history by date and switch silver and gold from full recompute (seconds at 68,784 hours) to incremental MERGE. Power BI Direct Lake has per-SKU limits, so gold would get pre-aggregated tables.

3. Why Azure SQL and not Cosmos DB, or just CSV files in the Lakehouse?
   The reference data is relational: meters point to sites and customers, the schema is fixed, rows are updated one at a time, and we want keys, CHECK constraints and column classifications. The free offer costs nothing. Cosmos DB is built for flexible JSON documents at large scale; we have 110 rows in three tables. CSV files in the Lakehouse would not be an operational store with constraints and per-column classification.

4. Why Direct Lake and not Import mode?
   Direct Lake reads the gold Delta files directly: no second copy and no refresh step, so a pipeline run shows in the report straight away. Import would need a scheduled refresh after every run and would duplicate the data. If a gold table outgrew the SKU's Direct Lake limits, we would pre-aggregate it or move up a SKU.

5. How do you know a rerun does not duplicate data?
   `nb_bronze` replaces the rows of the files it re-reads (Delta `replaceWhere` on `source_file`); `nb_silver` and `nb_gold` recompute their tables and overwrite them; silver keeps one row per hour (newest IESO file wins), and the DQ check `unique_target_time` fails the run if a duplicate appears. Evidence: two runs for the same date give identical counts `[TODO after T3.4]`.

6. How do you avoid leakage in the forecast, and why a seasonal-naive baseline?
   The forecast is issued at 08:15 EST on day D for the 24 hours of D+1. At that time IESO has published demand up to D-1, so every demand feature is at least 48 hours old, and a unit test changes all demand from D on and checks that no feature moves. Weather of the target day comes from the Open-Meteo Previous Runs API, the forecast made one or two days before each hour, which matches the lead the model gets at 08:15 the day before; before 2024 that archive is incomplete, so older years fall back to the Historical Forecast API (short lead). Trained and scored that way, the 2026 holdout MAPE is 2.90 %; the older short-lead setting gave 2.70 %, which was optimistic (3.07 % when rescored with production-lead weather). The live rows will measure the real error. The split is by time (train 2019 to 2024, early stopping on 2025, test 2026) plus a monthly rolling backtest from January 2025. The baseline is the same hour one week earlier, the usual simple benchmark for hourly load, and it is known at issue time. Results: (local run: holdout 2026 MAPE 2.90 % against 6.84 % for the naive baseline; quote the Fabric figures once T5.1 has run).

7. Why is the SQL server open to all Azure services, and why no private endpoints?
   The Fabric copy activity runs on shared infrastructure with no fixed IP we could allow on a trial. The rule only opens the login step; SQL authentication is still needed. Private endpoints need a virtual network plus a data gateway or Fabric managed private endpoints, which cost money and need admin rights we do not have. In production we would close public access and use private endpoints.

8. Why hash the customer id instead of encrypting it, and who can re-identify a customer?
   We need a stable key to join meters to customers without exposing the person; encryption is reversible by anyone holding the key and hides nothing more for our use. The salt sits in Key Vault, so nobody can rebuild the hash of ids 1 to 50 by trial. Re-identification needs the salt and SQL access: the Admin, and in our build also the Engineer, who can read secrets. We name that as a known gap (`docs/security.md`, section 8.1).

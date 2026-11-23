# Manual (browser-only) steps

These are the steps Fabric only lets a person do in the browser, in the order they must happen, with an owner and the exact names to type. Everything else is scripted (`infra/azure/*.ps1`, `infra/fabric/deploy_fabric.ps1`).

Status on 2026-11-23:
- The Azure foundation is deployed and verified (`docs/evidence/azure_foundation.md`).
- `ws_gridpulse` exists on a trial capacity that belongs to a classmate outside the team, and the batch pipelines have run (`docs/evidence/fabric_batch.md`). Step 0 is no longer a blocker; it stays below in case the workspace has to move to Nacir's own trial.
- Steps 1 to 7 are not done yet.

Owners: **Nacir** = Admin persona (subscription Owner, workspace Member). **Hamza** = Data Engineer (workspace Admin, because he created the workspace). **Omar** = Analyst (workspace Viewer). Roles as deployed: `docs/evidence/rbac.md`. Nobody in the team owns the capacity.

---

## 0. Fabric trial capacity (Nacir) (only if the workspace moves off the classmate's capacity)

On 2026-11-23, Nacir's login (the one used for the deployment) saw only the 7 capacities that already existed on 11-06:
- 6 FTL4 trials created between 10-19 and 10-22;
- one PPU capacity.

He is admin of none of them: the capacity admin API answered `PowerBINotAuthorizedException` for all 7. None of them is his, and the team rule is never to build on someone else's trial.

1. Sign in at https://app.fabric.microsoft.com with **the same account the CLI uses** (Nacir's UIR account), not a personal one.
2. Click the account picture (top right) and look under **Trial status**:
   - "Free trial: N days left" means the trial exists. Go to Settings (gear) > Admin portal > **Capacity settings** > **Trial** tab: the trial capacity is listed with its name `Trial-2026...`. Send that exact name to Hamza.
   - A **Start trial** button means the trial was never started. Click it:
     - region **Germany West Central** if the dialog offers a choice;
     - then **Start trial**, then **Got it**.
   - If Fabric says the tenant has reached its trial limit, stop and tell Hamza (option: ask a teacher or tenant admin).
3. Hamza then runs `fab api capacities` and checks that the new `Trial-202611...` capacity appears. He passes its name to `deploy_fabric.ps1 -CapacityName "<name>" -AssignRoles`.

## 1. Eventstream `es_meters` source and destination, key into Key Vault (Nacir, after the deploy)

1. `ws_gridpulse` > open `es_meters` (created empty by the deploy).
2. **Add source** > **Custom endpoint**. Source name: `src_meter_simulator` > **Add**.
3. **Add destination** > **Eventhouse**:
   - data ingestion mode **Event processing before ingestion**;
   - destination name `dst_eh_meter_readings`;
   - workspace `ws_gridpulse`, Eventhouse `eh_gridpulse`, KQL database `eh_gridpulse`;
   - table **existing** `meter_readings`;
   - input data format **JSON**, mapping `meter_readings_json`;
   - **Save**.
4. **Publish** (top right). Wait until both nodes show *Active*.
5. Click `src_meter_simulator` > **Keys** tab (protocol **Event Hub**, authentication **SAS key**) > copy **Connection string-primary key**. Do not paste it into chat, mail or the repo.
6. Put the copied value straight into Key Vault. In PowerShell on the laptop, logged in with `az login`:
   ```powershell
   $f = New-TemporaryFile
   Get-Clipboard | Set-Content $f -NoNewline -Encoding ascii
   az keyvault secret set --vault-name kv-hz2611-cdda -n es-meters-conn --file $f --encoding utf-8 -o none
   Remove-Item $f; Set-Clipboard -Value ' '
   ```
7. Test it: `uv run python realtime/simulator.py --kv-url https://kv-hz2611-cdda.vault.azure.net --rate 10`. After a minute, `meter_readings | count` in the KQL database should be about 600.

## 2. Outlook connection `con_outlook_alerts` (Hamza, before the second deploy run)

The tenant offers the connection type `MicrosoftOutlook` with OAuth2 only, so no script can create it. (Checked on 2026-11-23 with `GET /v1/connections/supportedConnectionTypes`; see `tests/fixtures/fabric_connection_types.json`.)

1. Fabric > Settings (gear) > **Manage connections and gateways** > **+ New** > **Cloud**.
2. Connection name `con_outlook_alerts`, connection type **Office 365 Outlook**, authentication **OAuth 2.0** > **Edit credentials** > sign in with the account that will send the mail > **Create**.
3. Rerun `powershell -File infra\fabric\deploy_fabric.ps1 -CapacityName "<trial name>"`. It now finds the connection and adds `mail_failure` to both pipelines.
4. Check the activity JSON, which was written from memory:
   - `fab export ws_gridpulse.Workspace/pl_daily_ingest.DataPipeline -o build/export -f`;
   - compare the `mail_failure` activity with `infra/fabric/gen_pipelines.py` `failure_path()`;
   - fix the generator if Fabric wrote it differently, and commit.

## 3. Semantic model `sm_gridpulse` (Hamza) and report `rpt_gridpulse` (Omar)

Prerequisites:
- `pl_backfill` has succeeded, so the 13 gold tables and `silver_dq_results` exist.
- Hamza and Omar have each clicked **Start trial** for the free Power BI individual trial the first time Fabric asks.

1. Hamza follows `powerbi/semantic_model_spec.md` section 11 (steps 1 to 13):
   - name `sm_gridpulse`, 14 tables, relationships R1 to R9;
   - date table `gold_dim_date` on `est_date`;
   - measures from `powerbi/measures.dax`;
   - then the checks of section 12.
2. Nacir gives Omar **temporary Contributor** (section 6 below).
3. Omar follows `powerbi/report_spec.md` section 7 (steps 1 to 22):
   - name `rpt_gridpulse`, 4 pages;
   - the "Live view (Q4)" button links to `rtd_gridpulse`;
   - one screenshot per page into `docs/evidence/`.
4. Export the semantic model in TMDL format (`fab export ws_gridpulse.Workspace/sm_gridpulse.SemanticModel -o powerbi/ -f`) and download the PBIX into `powerbi/`.

## 4. Real-Time Dashboard `rtd_gridpulse` (Nacir)

1. `ws_gridpulse` > **+ New item** > **Real-Time Dashboard** > name `rtd_gridpulse` > **Create**.
2. **New data source** > OneLake data hub > `eh_gridpulse` (KQL database) > **Connect**.
3. Add three tiles. For each: **+ Add tile**, paste the file content, **Run**, then **Apply changes**.
   - Tile **Q1 load per site, 5-min windows**: `realtime/kql/q1_5min_window.kql`, visual **Line chart** (x = window start, series = site_id).
   - Tile **Q2 abnormal sites (mean + 3 sigma)**: `realtime/kql/q2_anomaly.kql`, visual **Table**.
   - Tile **Q3 top 5 sites, last 15 min**: `realtime/kql/q3_top5.kql`, visual **Bar chart**.
4. **Manage** > **Auto refresh** > on, minimum interval **30 seconds**, default **30 seconds** > **Apply**. Then **Save**.
5. Screenshot while the simulator runs, into `docs/evidence/rtd_gridpulse.png`.

## 5. Activator `act_abnormal_demand` (Nacir)

1. In `rtd_gridpulse`, on the **Q2** tile: **...** > **Set alert**.
2. Condition: **On each event** (each row returned).
   - Action: **Send me an email**, to the team alert address (the `fabric.alertTo` value of `infra/local.settings.json`).
   - Subject `GridPulse: abnormal consumption at site @site_id`.
   - Check frequency: **every 1 minute**.
3. Save to a new Activator item named `act_abnormal_demand` in `ws_gridpulse` > **Create**.
4. Test it:
   - run `uv run python realtime/simulator.py --kv-url https://kv-hz2611-cdda.vault.azure.net --rate 10 --anomaly 5 3.0 120`;
   - note the minute of the injection and the minute the mail arrives;
   - screenshot the mail into `docs/evidence/`.
5. After the demo, **stop** the rule (Activator > rule > Stop), so no stray mails are sent.

## 6. Omar's temporary Contributor access (Nacir)

1. `ws_gridpulse` > **Manage access** > find Omar (Viewer, added by `-AssignRoles`) > change the role to **Contributor**.
2. When `rpt_gridpulse` is saved and exported: set it back to **Viewer** (least privilege for the Analyst persona in the demo). Note both dates in `docs/security.md` section 8.

## 7. Check: can a workspace Viewer read `bronze_customers` (PII)? (Omar + Hamza)

Not tested yet. The workspace and `bronze_customers` (50 rows) exist since 2026-11-23, and Omar is Viewer, so the test can run now. In Fabric, workspace Viewers are allowed to query a Lakehouse SQL analytics endpoint, so the expected answer is **yes**, which would be a finding.

1. Omar, as **Viewer**: `ws_gridpulse` > `lh_gridpulse` > switch to **SQL analytics endpoint**.
   - New SQL query: `SELECT TOP 5 full_name, email FROM dbo.bronze_customers;`
   - Screenshot the result or the error into `docs/evidence/viewer_pii_check.png`.
2. If rows come back, Hamza applies one of the fixes and Omar re-runs the query (expected: permission error):
   - **Preferred, no Fabric admin rights needed:** on the SQL analytics endpoint, Hamza runs
     ```sql
     DENY SELECT ON OBJECT::dbo.bronze_customers TO [<omar's UIR e-mail>];
     ```
   - **Alternative:** remove Omar from the workspace and share only `sm_gridpulse` + `rpt_gridpulse` with him (item permissions **Read**, without "Read all SQL endpoint data").
3. Write the result into `docs/security.md`, "Known gaps".

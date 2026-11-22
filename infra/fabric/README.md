# Fabric deployment

Everything GridPulse needs in Microsoft Fabric is created from this repo by
`deploy_fabric.ps1`, except six items that Fabric only lets you configure in the browser
(listed at the end). Status on 2026-11-22: **written and dry-run locally, not yet run against
Fabric** (no trial capacity yet). Expect small fixes on the first real run; the places most
likely to need one are marked "verify" below.

## Files

| File | Role |
|---|---|
| `../../fabric/<item>.<Type>/` | Item definitions in Fabric's Git format, with `{{TOKEN}}` placeholders for ids |
| `gen_pipelines.py` | Generates the two `pipeline-content.json` files (edit there, rerun, commit) |
| `render.py` | Fills the tokens from `ids.local.json`, validates the pipelines, adds the wheel to the environment, writes `build/fabric/` |
| `run_kql.py` | Runs `realtime/kql/00_tables.kql` on the Eventhouse (Kusto REST, your `az login` token) |
| `deploy_fabric.ps1` | The deployment, in order, idempotent, with `-DryRun` |
| `ids.local.json` | Written by the deploy, git-ignored |

## Order of a full deployment

1. Proposal sent, Azure foundation done: `infra/azure/deploy.ps1` (Key Vault with
   `sql-gpadmin-password` and `customer-hash-salt`, SQL server, free database), then
   `uv run python scripts/load_sql.py --schema --server sql-hz2611-cdda.database.windows.net`.
2. Nacir starts the 60-day Fabric trial (region Germany West Central) and notes the capacity
   name (`fab ls .capacities`).
3. `fab auth login` as yourself, then

   ```powershell
   powershell -File infra\fabric\deploy_fabric.ps1 -DryRun          # read the plan
   powershell -File infra\fabric\deploy_fabric.ps1 -CapacityName "<trial capacity>" -AssignRoles
   ```

   `-AssignRoles` (Hamza = Member, Omar = Viewer) needs the Admin persona's login.
4. The browser steps below.
5. First data: `fab job start ws_gridpulse.Workspace/pl_backfill.DataPipeline --wait`
   (all years, then model training). From the next morning `pl_daily_ingest` runs at 13:15 UTC.
6. Rerun the script after any change in `fabric/`: it re-imports every definition.

## What the dry run checks offline

`-DryRun` prints every `fab` command it would run and calls neither `fab` nor `az`. It still
builds the wheel (`uv build --offline`), renders every item with fake GUIDs, validates the
pipelines (every dependency exists, every notebook and connection reference is a GUID, no token
left) and parses the KQL file. The same checks run in `tests/unit/test_render.py`.

## Things to verify on the first real run

- **HTTP connection type name.** `fab mkdir .connections/...` needs Fabric's type name for an
  anonymous HTTP source. The script uses `HttpServer` and, if Fabric refuses it, prints the
  tenant's types that contain "Http" or "Web" and stops; rerun with `-HttpConnectionType <name>`.
- **SQL connection body.** Built from the format in the `fab` CLI source (`type` and
  `creationMethod` = `SQL`, parameters `server` and `database`, Basic credentials). The password
  goes from Key Vault into a temp file that is deleted right after the call.
- **Office 365 Outlook activity.** Its JSON (`type: Office365Outlook`, `inputs.path: /v2/Mail`)
  is written from memory of an exported pipeline. After creating `con_outlook_alerts` in the UI,
  export `pl_daily_ingest` (`fab export`) and align `gen_pipelines.py` with what Fabric wrote.
- **Kusto token scope** in `run_kql.py` (`https://kusto.kusto.windows.net/.default`). If refused,
  paste `00_tables.kql` into the KQL queryset once; the commands are idempotent.
- **Environment publish time.** The first publish installs `holidays` and the wheel and can take
  several minutes; `fab import` waits for it.

## Browser-only steps (reproducibility note for the report)

1. Start the Fabric trial (Nacir, account manager, region Germany West Central).
2. `es_meters`: add the Custom endpoint source and the Eventhouse destination (`meter_readings`,
   mapping `meter_readings_json`), then copy the Event Hub connection string into Key Vault
   (`az keyvault secret set --vault-name kv-hz2611-cdda -n es-meters-conn --file <file>`),
   never into chat or the repo.
3. `con_outlook_alerts` (Office 365 Outlook, OAuth), then rerun the deploy.
4. Semantic model `sm_gridpulse` from the Lakehouse and report `rpt_gridpulse`
   (`powerbi/semantic_model_spec.md`, `powerbi/report_spec.md`).
5. Real-Time Dashboard `rtd_gridpulse` from the KQL files in `realtime/kql/`.
6. Activator `act_abnormal_demand` on the q2 tile.

After each one, export the definition (`fab export ws_gridpulse.Workspace/<item> -o fabric/`)
and commit it, so the repo stays the source of truth.

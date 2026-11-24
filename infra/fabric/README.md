# Fabric deployment

Everything GridPulse needs in Microsoft Fabric is created from this repo by
`deploy_fabric.ps1`, except six items that Fabric only lets you configure in the browser
(listed at the end). Status on 2026-11-24: **run against Fabric on 2026-11-23**, on a classmate's
trial capacity in Germany West Central (our own accounts were refused a Fabric trial, see
`docs/security.md`). It took three runs: the first failed at the environment publish (the default
runtime uses Python 3.12, which our wheel does not support, now pinned to runtime 1.3), the second
reported the SQL connection as created when the API had answered HTTP 400 (fixed by
`Invoke-FabApi`, which now fails on any 4xx or 5xx), the third completed. Results in
`docs/evidence/fabric_batch.md`. The notes below say what each first-run check found.

## Files

| File | Role |
|---|---|
| `../../fabric/<item>.<Type>/` | Item definitions in Fabric's Git format, with `{{TOKEN}}` placeholders for ids |
| `gen_pipelines.py` | Generates the two `pipeline-content.json` files (edit there, rerun, commit) |
| `render.py` | Fills the tokens from `ids.local.json`, validates the pipelines, adds the wheel to the environment, writes `build/fabric/` |
| `run_kql.py` | Runs `realtime/kql/00_tables.kql` on the Eventhouse (Kusto REST, your `az login` token) |
| `deploy_fabric.ps1` | The deployment, in order, idempotent, with `-DryRun` |
| `ids.local.json` | Written by the deploy, git-ignored |
| `../local.settings.json` | Alert e-mails and persona object ids (also the Azure subscription and tenant ids), git-ignored; copy `../local.settings.example.json`. `-DryRun` uses the placeholders when it is missing |

## Order of a full deployment

1. Proposal sent, Azure foundation done: `infra/azure/deploy.ps1` (Key Vault with
   `sql-gpadmin-password` and `customer-hash-salt`, SQL server, free database), then
   `uv run python scripts/load_sql.py --schema --server sql-hz2611-cdda.database.windows.net`.
2. A Fabric trial capacity you can create workspaces on (region Germany West Central); note its
   name (`fab ls .capacities`).
3. `fab auth login` as yourself, then

   ```powershell
   powershell -File infra\fabric\deploy_fabric.ps1 -DryRun          # read the plan
   powershell -File infra\fabric\deploy_fabric.ps1 -CapacityName "<trial capacity>" -AssignRoles
   ```

   `-AssignRoles` gives each persona in `local.settings.json` its workspace role (Omar = Viewer).
   The signed-in creator is the workspace Admin and is skipped, so the only Admin is never demoted.
   On 2026-11-23 Hamza deployed, so he is Admin; Nacir was then added as Member by hand.
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

- **HTTP connection type name: checked 2026-11-23.** `GET /v1/connections/supportedConnectionTypes`
  on the UIR tenant lists `HttpServer` (creation method `HttpServer.Contents`, parameter `url`,
  Anonymous allowed); snapshot in `tests/fixtures/fabric_connection_types.json`, pinned by
  `tests/unit/test_fabric_contracts.py`. If Fabric still refuses it, the script prints the tenant's
  Http/Web types and stops; rerun with `-HttpConnectionType <name>`.
- **SQL connection body: checked against the API 2026-11-23.** `type` `SQL`, `creationMethod`
  `Sql` (the exact name the API lists; the first version sent `SQL`), parameters `server` and
  `database`, Basic credentials. The password goes from Key Vault into a temp file that is deleted
  right after the call. Created on 2026-11-23 (`con_sql_gridpulse`); the first attempt got
  HTTP 400 (most likely because the paused database had not woken up yet) and a retry succeeded.
- **Office 365 Outlook activity.** Its JSON (`type: Office365Outlook`, `inputs.path: /v2/Mail`)
  is written from memory of an exported pipeline. After creating `con_outlook_alerts` in the UI,
  export `pl_daily_ingest` (`fab export`) and align `gen_pipelines.py` with what Fabric wrote.
- **Kusto token scope.** `run_kql.py` now asks the cluster (`/v1/rest/auth/metadata`,
  `KustoServiceResourceId`) like azure-kusto-data does, falling back to
  `https://kusto.kusto.windows.net/.default`; it prints the scope it used. Ran on 2026-11-23:
  table `meter_readings` and mapping `meter_readings_json` exist. If refused on a new Eventhouse,
  paste `00_tables.kql` into the KQL queryset once (idempotent).
- **Environment publish time.** The first publish installs `holidays` and the wheel and can take
  several minutes; `fab import` waits for it. The environment must stay on runtime 1.3
  (`Setting/Sparkcompute.yml`): runtime 2.0 brings Python 3.12 and the publish fails.

## Browser-only steps (reproducibility note for the report)

1. Get a Fabric trial capacity (region Germany West Central). The self-service trial was refused
   for our accounts on the UIR tenant; we deploy on a classmate's trial capacity.
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

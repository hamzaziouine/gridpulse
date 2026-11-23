# Resource inventory and cleanup (deliverable 7)

Planned Azure and Fabric resources of GridPulse, with region, size, cost estimate, how each one gets created, its status, and how it gets removed. Status as of 2026-11-23: the Azure foundation is deployed (Key Vault, two secrets, SQL server, firewall, free-offer database with the reference rows, two tag policies), all under Nacir's account. Evidence: `docs/evidence/azure_foundation.md`. The Fabric workspace and its items were created on 2026-11-23 under Hamza's account, on a trial capacity that belongs to a classmate outside the team (`docs/evidence/fabric_batch.md`).

Cost estimates come from DESIGN section 3. Subscription: "Azure for Students" (owner Mohamed NACIR; the subscription and tenant ids are kept in the git-ignored `infra/local.settings.json`). Tags on every Azure resource: `project=cdda-gridpulse`, `owner=hamza.ziouine`, `course=CDDA-2627`.

## Azure (resource group `rg-hz2611-cdda`)

| Name | Type | Region | SKU / capacity | Monthly cost estimate | Created by | Status 2026-11-23 | Cleanup action |
|---|---|---|---|---|---|---|---|
| `rg-hz2611-cdda` | Resource group | germanywestcentral | n/a | $0 | created 2026-11-06 under Nacir's account | exists | deleted by `infra/azure/cleanup.ps1` (with everything in it) |
| `budget-cdda-20usd` | Cost Management budget (RG scope) | n/a | $20 per month, 2026-11-01 to 2027-03-31; mails at 50 % and 100 % actual, 100 % forecast, to Hamza and Nacir | $0 | created 2026-11-06 under Nacir's account | exists (spend 0.00 USD on 2026-11-06 and on 2026-11-23) | deleted with the RG |
| `kv-hz2611-cdda` | Key Vault | germanywestcentral | Standard (default), RBAC authorization, soft delete 7 days, purge protection off | under $0.10 (a few hundred operations) | `infra/azure/deploy.ps1` | created 2026-11-23 | deleted with the RG, then purged by `cleanup.ps1` |
| `sql-gpadmin-password` | Key Vault secret | (in the vault) | generated, 28 characters | included above | `deploy.ps1` | created 2026-11-23 | removed with the vault |
| `customer-hash-salt` | Key Vault secret | (in the vault) | 32 random bytes (hex), kept on reruns | included above | `deploy.ps1` | created 2026-11-23 | removed with the vault |
| `es-meters-conn` | Key Vault secret | (in the vault) | Eventstream custom endpoint connection string | included above | manual, copied from the Eventstream UI (PLAN T6.2) | not created yet | removed with the vault |
| `sql-hz2611-cdda` | Azure SQL logical server | germanywestcentral | minimum TLS 1.2, SQL admin `gpadmin`, optional Entra admin (Nacir) | $0 | `deploy.ps1` | created 2026-11-23 (TLS 1.2) | deleted with the RG |
| `AllowAzureServices`, `laptop-<user>` | SQL server firewall rules | (on the server) | 0.0.0.0 rule + the laptop's public IP | $0 | `deploy.ps1` | created 2026-11-23 | deleted with the server |
| `sqldb-hz2611-gridpulse` | Azure SQL Database | germanywestcentral | General Purpose serverless, Gen5, 2 vCores, free offer (100,000 vCore-seconds per month, auto-pause when used up), local backup redundancy | $0 (free offer; it pauses instead of billing) | `deploy.ps1`; schema, classifications and seed rows by `scripts/load_sql.py --schema` | created 2026-11-23, useFreeLimit true, AutoPause; 10 / 50 / 50 rows | deleted with the RG |
| `require-tag-project` | Policy assignment (RG scope), built-in `871b6d14-10aa-478d-b590-94f262ecfa99`, deny | n/a | n/a | $0 | `infra/azure/policy_assignments.ps1` | assigned 2026-11-23, denial tested | removed with the RG |
| `require-tag-owner` | Policy assignment (RG scope), same definition, deny | n/a | n/a | $0 | `policy_assignments.ps1` | assigned 2026-11-23, denial tested | removed with the RG |
| `sys.regionrestriction` | Policy assignment (subscription scope, inherited) | n/a | allowed: switzerlandnorth, italynorth, denmarkeast, germanywestcentral, polandcentral | $0 | the subscription, not us | exists | none (not ours) |
| Role assignments at RG scope: Nacir Key Vault Secrets Officer; Hamza Contributor, Resource Policy Contributor, Key Vault Secrets Officer; Omar Reader. Not assigned: Nacir Key Vault Administrator, SQL Entra admin | Azure RBAC | n/a | n/a | $0 | Nacir (the first one under his session from Hamza's laptop, the others by Nacir at 19:25 to 19:26 UTC) | created 2026-11-23 (`docs/evidence/rbac.md`) | removed with the RG |
| `stgpulsepolicytest` | Storage account used only by the policy test | germanywestcentral | Standard_LRS | $0 | `policy_assignments.ps1 -Test` | refused by the policy on 2026-11-23, never created | none |

## Fabric (workspace `ws_gridpulse`)

Fabric items have no SKU of their own; they all run on the workspace's capacity. Region = capacity region = Germany West Central. Status read back on 2026-11-23 with `fab ls ws_gridpulse.Workspace`.

| Name | Type | Region | SKU / capacity | Monthly cost estimate | Created by | Status 2026-11-23 | Cleanup action |
|---|---|---|---|---|---|---|---|
| Classmate's trial capacity | Fabric trial capacity | Germany West Central | FTL4 (4 capacity units), created 2026-10-19, 60 days | $0 | a classmate outside the team, not us | in use; expected end around 2026-12-18 (estimate) | not ours: we only move `ws_gridpulse` off it or delete the workspace |
| `ws_gridpulse` | Workspace | Germany West Central | on the FTL4 trial | $0 | `infra/fabric/deploy_fabric.ps1 -CapacityName ... -AssignRoles`, signed in as Hamza | created 2026-11-23; Hamza Admin, Nacir Member, Omar Viewer | `fab rm ws_gridpulse.Workspace -f` (Admin), deletes every item below |
| `lh_gridpulse` | Lakehouse (with its SQL analytics endpoint), folders `Files/bronze/*`, `Files/libs` | same | trial | $0 | `deploy_fabric.ps1` | created 2026-11-23; 30 Delta tables after the backfill and two daily runs | with the workspace |
| `env_gridpulse` | Environment (gridpulse wheel + `holidays`) | same | Runtime 1.3, starter pool, 4-core driver and executors, 1 to 2 executors | $0 | `deploy_fabric.ps1` (`fab import`, publish can take minutes) | created and published 2026-11-23 | with the workspace |
| `nb_bronze`, `nb_silver`, `nb_gold` | Notebooks | same | trial (Spark) | $0 | `deploy_fabric.ps1` from `fabric/*.Notebook` | created 2026-11-23, run in the backfill and two daily runs | with the workspace |
| `nb_forecast`, `nb_predict` | Notebooks | same | trial (Spark) | $0 | `deploy_fabric.ps1` | created 2026-11-23; `nb_forecast` run once (backfill), `nb_predict` twice | with the workspace |
| `pl_daily_ingest` | Data pipeline + daily schedule 13:15 UTC, 2026-11-24 to 2026-12-17 | same | trial | $0 | `deploy_fabric.ps1` (definition from `infra/fabric/gen_pipelines.py`, ids filled by `render.py`) | created 2026-11-23, run twice by hand; no failure mail yet; first scheduled run pending | turn the schedule off first, then with the workspace |
| `pl_backfill` | Data pipeline (one-off) | same | trial | $0 | `deploy_fabric.ps1` | created 2026-11-23, run once (63.5 min) | with the workspace |
| `con_ieso_http`, `con_openmeteo_hist`, `con_openmeteo_fc`, `con_openmeteo_prev`, `con_sql_gridpulse` | Fabric connections (tenant-level, outside the workspace), owned by Hamza | n/a | n/a | $0 | `deploy_fabric.ps1` (SQL password from Key Vault through a temp file) | created 2026-11-23 | delete by hand in Settings > Manage connections and gateways; workspace deletion does not remove them |
| `con_outlook_alerts` | Fabric connection, OAuth (Office 365 Outlook) | n/a | n/a | $0 | UI only (T3.6); rerun the deploy afterwards so the mail activity is added | not created yet | delete by hand, as above |
| `es_meters` | Eventstream (custom endpoint source, Eventhouse destination) | same | trial | $0 | empty item by `deploy_fabric.ps1`; source and destination in the UI | created 2026-11-23, empty (no source, no destination) | with the workspace |
| `eh_gridpulse` | Eventhouse + KQL database, table `meter_readings` (7-day retention) | same | trial | $0 | `deploy_fabric.ps1` + `infra/fabric/run_kql.py` (runs `realtime/kql/00_tables.kql`) | created 2026-11-23; table and mapping exist, 0 rows | with the workspace |
| `kq_gridpulse` | KQL queryset (Q1, Q2, Q3) | same | trial | $0 | UI, from `realtime/kql/*.kql` | not created yet | with the workspace |
| `rtd_gridpulse` | Real-Time Dashboard | same | trial | $0 | UI (T6.5) | not created yet | with the workspace |
| `act_abnormal_demand` | Activator | same | trial | $0 | UI (T6.6) | not created yet | stop the rule first (no stray mails), then with the workspace |
| `exp_gridpulse_forecast` | ML experiment (MLflow) | same | trial | $0 | created by `nb_forecast` | created 2026-11-23 (backfill) | with the workspace; metrics exported to `docs/evidence/` first |
| `nb_forecast` (ML experiment) | ML experiment created by Fabric as the notebook's default | same | trial | $0 | Fabric, automatically | created 2026-11-23, not used by our code | with the workspace |
| `gridpulse_lgbm` | ML model (registry) | same | trial | $0 | registered by `nb_forecast` | created 2026-11-23, version 1 used by `nb_predict` | with the workspace |
| `sm_gridpulse` | Semantic model, Direct Lake | same | trial | $0 | UI (T7.1), then TMDL export | not created yet | with the workspace |
| `rpt_gridpulse` | Power BI report | same | trial | $0 | UI (Omar, T7.2) | not created yet | with the workspace; PBIX copy stays in `powerbi/` |
| GitHub connection for Git integration (if used) | Fabric connection + fine-grained GitHub token | n/a | n/a | $0 | Fabric API (T1F.5) | not created (`[TO DECIDE: set up Git integration or drop it]`) | delete the connection, revoke the token on GitHub |

## Outside Azure and Fabric

| Name | Type | Cost | Cleanup action |
|---|---|---|---|
| `realtime/simulator.py` process | Python process on a team laptop | $0 | Ctrl+C |
| Power BI individual trials (Hamza, Omar) | licences | $0 | expire on their own |
| `data/raw/`, `data/lakehouse/`, `mlruns/` | local files, git-ignored | $0 | keep or delete locally; never committed |

Expected total: under $2 for the whole project, against the $20 monthly budget alert (DESIGN section 3). The only item that can bill is Key Vault operations. If the trial were not available, PLAN risk 1 estimates a pay-as-you-go F2 capacity at about $0.36 per hour, paused when idle; we have not used one, and the price should be checked on the Azure pricing page before any decision.

## Cleanup checklist (after grading, in this order)

Cleanup happens only after the grade is published (PLAN T12.2), with Nacir's agreement. The table above goes into the report before step 1.

1. Freeze the evidence that depends on live resources:
   - `powershell -File infra\azure\inventory.ps1 | Out-File -Encoding utf8 docs\evidence\inventory.md`
   - `fab ls ws_gridpulse.Workspace` copied into the same file.
2. Stop the simulator (Ctrl+C). Check in `kq_gridpulse` that `meter_readings | where ts > ago(5m) | count` returns 0.
3. Stop the Activator rule `act_abnormal_demand` and turn off the schedule of `pl_daily_ingest`, so nothing fires during cleanup.
4. Export what we keep:
   - `fab bulk-export ws_gridpulse.Workspace -o .\infra\fabric\definitions` and commit;
   - download `rpt_gridpulse` as PBIX into `powerbi/`;
   - MLflow metrics into `docs/evidence/model_metrics.md`;
   - screenshots into `docs/evidence/`.
5. Delete the workspace (Hamza, workspace Admin): `fab rm ws_gridpulse.Workspace -f`. Check that `fab ls` no longer lists it.
6. Delete the Fabric connections, which live outside the workspace: `con_ieso_http`, `con_openmeteo_hist`, `con_openmeteo_fc`, `con_openmeteo_prev`, `con_sql_gridpulse`, `con_outlook_alerts`, and the GitHub connection if one was made. Revoke the GitHub token.
7. Delete the Azure resource group: `powershell -File infra\azure\cleanup.ps1`. The script refuses any RG other than `rg-hz2611-cdda` and the protected `TP6` and `tp1`, lists what it will delete, and asks for the RG name to be typed back. It removes the SQL server and database, the Key Vault, the policy and role assignments at RG scope, and the budget.
8. Key Vault purge. `cleanup.ps1` runs `az keyvault purge -n kv-hz2611-cdda` but ignores its errors. Check with:

   ```powershell
   az keyvault list-deleted --query "[?name=='kv-hz2611-cdda'].name" -o tsv
   ```

   An empty result means it is purged. Otherwise run `az keyvault purge -n kv-hz2611-cdda` again (Nacir, if Hamza's role is already gone with the RG).
9. Confirm Nacir's other groups are untouched. `cleanup.ps1` ends by printing the remaining groups; `TP6` and `tp1` must be there and `rg-hz2611-cdda` must not. Also: `az group exists -n rg-hz2611-cdda` prints `false`.
10. Final inventory. Run `powershell -File infra\azure\inventory.ps1` once more and keep its output. With the RG gone, it stops at `az resource list` with a "resource group not found" error; that error is the evidence that nothing is left. The table of step 1 stays the inventory shown in the report.
11. The next month, the budget mail stays quiet. The trial capacity and the Power BI trials expire on their own.

## Regenerating the live table

`infra/azure/inventory.ps1` is read-only. It signs in to the right subscription and tenant (it refuses any other), then prints Markdown:

- every resource in `rg-hz2611-cdda` with type, location and tags;
- the role assignments on the RG, inherited ones included;
- the policy assignments on the RG and above;
- the budget amount and the month-to-date spend.

```powershell
powershell -File infra\azure\inventory.ps1 | Out-File -Encoding utf8 docs\evidence\inventory.md
```

Use `Out-File -Encoding utf8` rather than `>`: in Windows PowerShell 5.1, `>` can write UTF-16, which shows up badly on GitHub.

The script covers Azure only. For Fabric, add the output of `fab ls ws_gridpulse.Workspace`. SKUs are not in either output, so the SKU column of the tables above stays the reference. `[TODO after T12.1: paste the generated output under this heading before the report freeze]`

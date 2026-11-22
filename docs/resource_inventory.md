# Resource inventory and cleanup (deliverable 7)

Planned Azure and Fabric resources of GridPulse, with region, size, cost estimate, how each one gets created, its status, and how it gets removed. Status as of 2026-11-22: only the resource group `rg-hz2611-cdda` and the budget `budget-cdda-20usd` exist (both created on 2026-11-06 under Nacir's account). Everything else is "not created yet".

Cost estimates come from DESIGN section 3. Subscription: "Azure for Students" (owner Mohamed NACIR, id `<subscription-guid>`). Tags on every Azure resource: `project=cdda-gridpulse`, `owner=hamza.ziouine`, `course=CDDA-2627`.

## Azure (resource group `rg-hz2611-cdda`)

| Name | Type | Region | SKU / capacity | Monthly cost estimate | Created by | Status 2026-11-22 | Cleanup action |
|---|---|---|---|---|---|---|---|
| `rg-hz2611-cdda` | Resource group | germanywestcentral | n/a | $0 | created 2026-11-06 under Nacir's account | exists | deleted by `infra/azure/cleanup.ps1` (with everything in it) |
| `budget-cdda-20usd` | Cost Management budget (RG scope) | n/a | $20 per month, 2026-11-01 to 2027-03-31; mails at 50 % and 100 % actual, 100 % forecast, to Hamza and Nacir | $0 | created 2026-11-06 under Nacir's account | exists (spend 0.00 USD on 2026-11-06) | deleted with the RG |
| `kv-hz2611-cdda` | Key Vault | germanywestcentral | Standard (default), RBAC authorization, soft delete 7 days, purge protection off | under $0.10 (a few hundred operations) | `infra/azure/deploy.ps1` | not created yet | deleted with the RG, then purged by `cleanup.ps1` |
| `sql-gpadmin-password` | Key Vault secret | (in the vault) | generated, 28 characters | included above | `deploy.ps1` | not created yet | removed with the vault |
| `customer-hash-salt` | Key Vault secret | (in the vault) | 32 random bytes (hex), kept on reruns | included above | `deploy.ps1` | not created yet | removed with the vault |
| `es-meters-conn` | Key Vault secret | (in the vault) | Eventstream custom endpoint connection string | included above | manual, copied from the Eventstream UI (PLAN T6.2) | not created yet | removed with the vault |
| `sql-hz2611-cdda` | Azure SQL logical server | germanywestcentral | minimum TLS 1.2, SQL admin `gpadmin`, optional Entra admin (Nacir) | $0 | `deploy.ps1` | not created yet | deleted with the RG |
| `AllowAzureServices`, `laptop-<user>` | SQL server firewall rules | (on the server) | 0.0.0.0 rule + the laptop's public IP | $0 | `deploy.ps1` | not created yet | deleted with the server |
| `sqldb-hz2611-gridpulse` | Azure SQL Database | germanywestcentral | General Purpose serverless, Gen5, 2 vCores, free offer (100,000 vCore-seconds per month, auto-pause when used up), local backup redundancy | $0 (free offer; it pauses instead of billing) | `deploy.ps1`; schema, classifications and seed rows by `scripts/load_sql.py --schema` | not created yet | deleted with the RG |
| `require-tag-project` | Policy assignment (RG scope), built-in `871b6d14-10aa-478d-b590-94f262ecfa99`, deny | n/a | n/a | $0 | `infra/azure/policy_assignments.ps1` | not created yet | removed with the RG |
| `require-tag-owner` | Policy assignment (RG scope), same definition, deny | n/a | n/a | $0 | `policy_assignments.ps1` | not created yet | removed with the RG |
| `sys.regionrestriction` | Policy assignment (subscription scope, inherited) | n/a | allowed: switzerlandnorth, italynorth, denmarkeast, germanywestcentral, polandcentral | $0 | the subscription, not us | exists | none (not ours) |
| Role assignments: Hamza Contributor + Resource Policy Contributor, Omar Reader (RG); Nacir Key Vault Administrator, Hamza Key Vault Secrets Officer | Azure RBAC | n/a | n/a | $0 | Nacir, commands of PLAN 5.3 | not created yet | removed with the RG |
| `stgpulsepolicytest` | Storage account used only by the policy test | germanywestcentral | Standard_LRS | $0 | `policy_assignments.ps1 -Test` | never meant to exist: the policy refuses it; if the policy is not effective yet, the script deletes it right away | none |

## Fabric (workspace `ws_gridpulse`)

Fabric items have no SKU of their own; they all run on the workspace's capacity. Region = capacity region = Germany West Central.

| Name | Type | Region | SKU / capacity | Monthly cost estimate | Created by | Status 2026-11-22 | Cleanup action |
|---|---|---|---|---|---|---|---|
| Nacir's trial capacity | Fabric trial capacity | Germany West Central | FTL4 (4 capacity units), 60 days | $0 | Nacir, Start trial in the Fabric UI | not started yet | expires on its own after 60 days |
| `ws_gridpulse` | Workspace | Germany West Central | on the FTL4 trial | $0 | `infra/fabric/deploy_fabric.ps1 -CapacityName ... -AssignRoles` (roles need the Admin's login) | not created yet | `fab rm ws_gridpulse.Workspace -f` (Admin), deletes every item below |
| `lh_gridpulse` | Lakehouse (with its SQL analytics endpoint), folders `Files/bronze/*`, `Files/libs` | same | trial | $0 | `deploy_fabric.ps1` | not created yet | with the workspace |
| `env_gridpulse` | Environment (gridpulse wheel + `holidays`) | same | trial | $0 | `deploy_fabric.ps1` (`fab import`, publish can take minutes) | not created yet | with the workspace |
| `nb_bronze`, `nb_silver`, `nb_gold` | Notebooks | same | trial (Spark) | $0 | `deploy_fabric.ps1` from `fabric/*.Notebook` | not created yet (tested locally) | with the workspace |
| `nb_forecast`, `nb_predict` | Notebooks | same | trial (Spark) | $0 | `deploy_fabric.ps1` | not created yet (files written; local backtest in progress on 2026-11-22) | with the workspace |
| `pl_daily_ingest` | Data pipeline (13 activities) + daily schedule 13:15 UTC | same | trial | $0 | `deploy_fabric.ps1` (definition from `infra/fabric/gen_pipelines.py`, ids filled by `render.py`) | not created yet | turn the schedule off first, then with the workspace |
| `pl_backfill` | Data pipeline (one-off, 10 activities) | same | trial | $0 | `deploy_fabric.ps1` | not created yet | with the workspace |
| `con_ieso_http`, `con_openmeteo_hist`, `con_openmeteo_fc`, `con_sql_gridpulse` | Fabric connections (tenant-level, outside the workspace) | n/a | n/a | $0 | `deploy_fabric.ps1` (SQL password from Key Vault through a temp file) | not created yet | delete by hand in Settings > Manage connections and gateways; workspace deletion does not remove them |
| `con_outlook_alerts` | Fabric connection, OAuth (Office 365 Outlook) | n/a | n/a | $0 | UI only (T3.6); rerun the deploy afterwards so the mail activity is added | not created yet | delete by hand, as above |
| `es_meters` | Eventstream (custom endpoint source, Eventhouse destination) | same | trial | $0 | empty item by `deploy_fabric.ps1`; source and destination in the UI | not created yet | with the workspace |
| `eh_gridpulse` | Eventhouse + KQL database, table `meter_readings` (7-day retention) | same | trial | $0 | `deploy_fabric.ps1` + `infra/fabric/run_kql.py` (runs `realtime/kql/00_tables.kql`) | not created yet | with the workspace |
| `kq_gridpulse` | KQL queryset (Q1, Q2, Q3) | same | trial | $0 | UI, from `realtime/kql/*.kql` | not created yet | with the workspace |
| `rtd_gridpulse` | Real-Time Dashboard | same | trial | $0 | UI (T6.5) | not created yet | with the workspace |
| `act_abnormal_demand` | Activator | same | trial | $0 | UI (T6.6) | not created yet | stop the rule first (no stray mails), then with the workspace |
| `exp_gridpulse_forecast` | ML experiment (MLflow) | same | trial | $0 | created by `nb_forecast` | not created yet | with the workspace; metrics exported to `docs/evidence/` first |
| `gridpulse_lgbm` | ML model (registry) | same | trial | $0 | registered by `nb_forecast` | not created yet | with the workspace |
| `sm_gridpulse` | Semantic model, Direct Lake | same | trial | $0 | UI (T7.1), then TMDL export | not created yet | with the workspace |
| `rpt_gridpulse` | Power BI report | same | trial | $0 | UI (Omar, T7.2) | not created yet | with the workspace; PBIX copy stays in `powerbi/` |
| GitHub connection for Git integration (if used) | Fabric connection + fine-grained GitHub token | n/a | n/a | $0 | Fabric API (T1F.5) | not created yet | delete the connection, revoke the token on GitHub |

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
5. Delete the workspace (Nacir, workspace Admin): `fab rm ws_gridpulse.Workspace -f`. Check that `fab ls` no longer lists it.
6. Delete the Fabric connections, which live outside the workspace: `con_ieso_http`, `con_openmeteo_hist`, `con_openmeteo_fc`, `con_sql_gridpulse`, `con_outlook_alerts`, and the GitHub connection if one was made. Revoke the GitHub token.
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

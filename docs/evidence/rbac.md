# Role assignments as deployed (2026-11-23)

Read back on 2026-11-23, signed in as Hamza. Subscription id and role-assignment ids are left out.

## 1. Azure RBAC on `rg-hz2611-cdda`

`az role assignment list -g rg-hz2611-cdda` (direct assignments at the resource-group scope):

| Principal | Role | Scope | Created (UTC) | Created by |
|---|---|---|---|---|
| Mohamed NACIR | Key Vault Secrets Officer | `rg-hz2611-cdda` | 2026-11-23 14:34:05 | Nacir's session |
| Hamza ZIOUINE | Contributor | `rg-hz2611-cdda` | 2026-11-23 19:25:41 | Nacir |
| Hamza ZIOUINE | Resource Policy Contributor | `rg-hz2611-cdda` | 2026-11-23 19:25:45 | Nacir |
| Hamza ZIOUINE | Key Vault Secrets Officer | `rg-hz2611-cdda` | 2026-11-23 19:25:51 | Nacir |
| Omar MOUNABBIH | Reader | `rg-hz2611-cdda` | 2026-11-23 19:26:00 | Nacir |

Inherited, not listed above: Nacir is Owner of the "Azure for Students" subscription (checked on 2026-11-23 before the deployment), which covers this RG and his other groups. Tenant-level inherited assignments of UIR staff are left out on purpose.

The 14:34 assignment was created from Hamza's laptop under Nacir's signed-in session, together with the rest of the Azure foundation (`docs/security.md`, section 8.1). The 19:25 to 19:26 assignments were made by Nacir.

Not assigned, although `docs/security.md` once planned it:

- Key Vault Administrator for Nacir. As subscription Owner he can still grant himself any vault role.
- An Entra admin on the SQL server: `az sql server ad-admin list -g rg-hz2611-cdda -s sql-hz2611-cdda` returns `[]`. The server only has the SQL login `gpadmin`.
- Contained SQL users and `db_datareader` / `db_datawriter` for Hamza.

Checked: Hamza's Key Vault Secrets Officer works (`az keyvault secret show --vault-name kv-hz2611-cdda -n sql-gpadmin-password --query id` returns the id, value not printed). Not checked yet: Omar's expected 403 on the same command.

## 2. Fabric workspace roles on `ws_gridpulse`

`fab acl ls ws_gridpulse.Workspace`:

| Role | Person | Type |
|---|---|---|
| Admin | Hamza ZIOUINE | User |
| Member | Mohamed NACIR | User |
| Viewer | Omar MOUNABBIH | User |

Hamza is Admin because he created the workspace (`deploy_fabric.ps1`, signed in as himself). Omar was added as Viewer by the same script (`-AssignRoles`); Nacir was added as Member after the workspace existed.

Capacity: the workspace sits on a trial capacity owned by a classmate outside the team (`docs/evidence/fabric_batch.md`, section 1). None of us is capacity admin.

Not checked yet: whether Omar, as Viewer, can query `bronze_customers` through the SQL analytics endpoint (`docs/MANUAL_STEPS.md`, step 7).

# Azure foundation: deployment evidence (2026-11-23)

Real CLI output from the first deployment, run from the team laptop under the Admin persona's login (Nacir, Owner of the "Azure for Students" subscription). Redactions: subscription id, role-assignment ids, laptop IP and e-mail addresses. Nothing else was edited.

## 1. `infra/azure/deploy.ps1` (first successful run)

Before that run, Nacir was given **Key Vault Secrets Officer** at the resource-group scope. In RBAC mode, creating a vault grants no right to write secrets, not even to the subscription Owner.

```
Signed in as <admin persona> on 'Azure for Students'

== Resource group rg-hz2611-cdda

== Key Vault kv-hz2611-cdda
exists

== Secret sql-gpadmin-password
generated and stored

== Secret customer-hash-salt
generated and stored

== SQL server sql-hz2611-cdda
created

== SQL firewall
AllowAzureServices + laptop-mohamed-nacir (<laptop-ip>)

== Database sqldb-hz2611-gridpulse (free offer)
created

== Verify

KeyVault : kv-hz2611-cdda
SqlFqdn  : sql-hz2611-cdda.database.windows.net
Database : sqldb-hz2611-gridpulse
FreeTier : True
OnLimit  : AutoPause
Status   : Online
```

The vault line says "exists" because the first attempt created the vault and then stopped at the secret step (bug 19 in the project log: the helper lost the error text, so the "secret not found" answer was not recognised and the script refused to generate the password). Running the script a second time after the fix changed nothing: every step printed `exists`, `exists (reused)` or `exists (kept ...)`.

Database properties read back with `az sql db show`:

| Property | Value |
|---|---|
| SKU | GP_S_Gen5, 2 vCores, serverless, min 0.5 vCore |
| `useFreeLimit` | true |
| `freeLimitExhaustionBehavior` | AutoPause |
| Auto-pause delay | 60 min |
| Max size | 32 GB |
| Backup storage redundancy | Local |

Server: `minimalTlsVersion` 1.2, tags `course=CDDA-2627, owner=hamza.ziouine, project=cdda-gridpulse`. Key Vault: RBAC authorization true, SKU standard, soft delete 7 days, secrets `customer-hash-salt` and `sql-gpadmin-password` (values never printed).

## 2. `infra/azure/policy_assignments.ps1 -Test`

```
require-tag-project assigned
require-tag-owner assigned

display                          name
-------                          ----
GridPulse: require tag 'project' require-tag-project
GridPulse: require tag 'owner'   require-tag-owner

DENIED by policy, as expected:
ERROR: (RequestDisallowedByPolicy) Resource 'stgpulsepolicytest' was disallowed by policy.
Policy identifiers: '[{"policyAssignment":{"name":"GridPulse: require tag 'project'",
"id":"/subscriptions/<subscription-id>/resourceGroups/rg-hz2611-cdda/providers/Microsoft.Authorization/policyAssignments/require-tag-project"},
"policyDefinition":{"name":"Require a tag on resources",
"id":"/providers/Microsoft.Authorization/policyDefinitions/871b6d14-10aa-478d-b590-94f262ecfa99","version":"1.0.1"}},
{"policyAssignment":{"name":"GridPulse: require tag 'owner'", ... "require-tag-owner"}, ...}]'.
Code: RequestDisallowedByPolicy
```

The deny took effect at once: the untagged storage account was refused and never created.

## 3. `scripts/load_sql.py --schema --server sql-hz2611-cdda.database.windows.net`

The admin password is read from Key Vault with DefaultAzureCredential. It is never typed and never written to disk.

```
rows: {'sites': 10, 'customers': 50, 'meters': 50}, schema batches: 3
schema: 3 batches executed
inserted {'sites': 10, 'customers': 50, 'meters': 50}
verified {'sites': 10, 'customers': 50, 'meters': 50}
  classified customers.email: Confidential - GDPR
  classified customers.full_name: Confidential - GDPR
  classified customers.phone: Confidential - GDPR
  classified customers.postal_code: Confidential
  classified customers.street_address: Confidential - GDPR
```

A second run without `--schema` gave the same 10 / 50 / 50 rows, so the load is idempotent.

## 4. Inventory (`infra/azure/inventory.ps1`, GridPulse scope only)

| Name | Type | Location | Tags |
|---|---|---|---|
| kv-hz2611-cdda | Microsoft.KeyVault/vaults | germanywestcentral | course=CDDA-2627, owner=hamza.ziouine, project=cdda-gridpulse |
| sql-hz2611-cdda | Microsoft.Sql/servers | germanywestcentral | course=CDDA-2627, owner=hamza.ziouine, project=cdda-gridpulse |
| sql-hz2611-cdda/master | Microsoft.Sql/servers/databases | germanywestcentral | (system database) |
| sql-hz2611-cdda/sqldb-hz2611-gridpulse | Microsoft.Sql/servers/databases | germanywestcentral | course=CDDA-2627, owner=hamza.ziouine, project=cdda-gridpulse |

Role assignments that GridPulse relies on:
- Nacir: Owner at subscription scope (pre-existing, Azure for Students).
- Nacir: Key Vault Secrets Officer at RG scope (granted 2026-11-23).

The inventory also lists inherited assignments made by the university tenant administrators. They are left out here.

Policy assignments on the RG: `require-tag-project`, `require-tag-owner`. The subscription-level allowed-regions restriction is also inherited.

Budget `budget-cdda-20usd`: 20 USD per month, **spent this month: 0.0 USD**, read on 2026-11-23 after the deployment.

# 8. Security and governance (report section 8, draft)

Draft, status of 2026-11-23. In Azure, `rg-hz2611-cdda` holds the Key Vault with two secrets, the SQL server and its free-offer database with the reference rows, and the two tag policies (`docs/evidence/azure_foundation.md`). In Fabric, `ws_gridpulse` exists with the Lakehouse, environment, notebooks, pipelines, an empty Eventstream and an Eventhouse with no data; the backfill and two daily runs succeeded (`docs/evidence/fabric_batch.md`). Roles as deployed are in `docs/evidence/rbac.md`. Every control has a status in section 8.8; a control is called "demonstrated in cloud" only once there is evidence for it in `docs/evidence/`.

The brief (section 4) asks that security be visible in the architecture. In `docs/architecture.svg` it is the governance band at the bottom and the resource group box on the left.

## 8.1 Identities, personas and least privilege

The subscription belongs to Nacir (Azure for Students). The Azure foundation (Key Vault, secrets, SQL server and database, policies, Nacir's Key Vault role) was deployed on 2026-11-23 from Hamza's laptop under Nacir's signed-in session, because no other member had a role yet. `[TO CONFIRM: Nacir's written agreement]` The Azure activity log therefore shows Nacir for those actions. From 2026-11-23 19:25 UTC, when Nacir assigned the roles of `docs/evidence/rbac.md`, Hamza works under his own UIR account (tenant `uir.ac.ma`) for Azure and Fabric, and every Fabric item was created under it. Sharing a session is not acceptable in production; we would use a service principal for deployments.

The Fabric workspace runs on a trial capacity that belongs to a classmate outside the team, not to Nacir: his own trial was not visible from our accounts (`docs/evidence/fabric_batch.md`, section 1). None of us is capacity admin.

Permissions are granted at four levels, because Azure and Fabric each have their own permission system:

1. Azure RBAC on the resource group `rg-hz2611-cdda` (control plane: create, change, delete resources).
2. Key Vault data-plane roles (the vault runs in RBAC mode, so there are no access policies).
3. Azure SQL database roles (`db_datareader`, `db_datawriter`), to be granted to contained Entra users (planned; none exists yet).
4. Fabric workspace roles on `ws_gridpulse` (Admin, Member, Contributor, Viewer).

### Permission matrix as deployed on 2026-11-23

Read back on 2026-11-23 (`docs/evidence/rbac.md`). Cells marked "planned" were in the design but are not assigned.

| Persona | Person | Azure RBAC, scope `rg-hz2611-cdda` | Key Vault `kv-hz2611-cdda` | Azure SQL `sqldb-hz2611-gridpulse` | Fabric `ws_gridpulse` |
|---|---|---|---|---|---|
| Admin | Mohamed NACIR | Owner (inherited: he owns the "Azure for Students" subscription) | Key Vault Secrets Officer (planned: Key Vault Administrator) | none (planned: Entra admin of `sql-hz2611-cdda`; `ad-admin list` is empty) | Member |
| Data Engineer | Hamza ZIOUINE | Contributor + Resource Policy Contributor | Key Vault Secrets Officer | none (planned: `db_datareader` + `db_datawriter`; he connects as `gpadmin` with the password from Key Vault) | Admin (he created the workspace) |
| Analyst | Omar MOUNABBIH | Reader | none | none | Viewer (planned: Contributor for a few days while he builds the report, then back to Viewer) |

The proposal had a fourth member; nobody joined, so there is no fourth persona.

Why each grant is the minimum we could find:

- Admin. Nacir already holds Owner on the subscription; we cannot remove that. We therefore put every "grant access" power on him in Azure. Owner does not include Key Vault data access in RBAC mode, so he got Key Vault Secrets Officer at RG scope before the first deployment (the design said Key Vault Administrator). The SQL Entra admin is not set yet. In Fabric he is a workspace Member, not Admin: Hamza created the workspace and the capacity is not Nacir's.
- Data Engineer. Contributor can create and delete resources in the RG but cannot assign roles (`Microsoft.Authorization/*/write` is excluded), so Hamza cannot raise his own rights or anyone else's. Contributor cannot write policy assignments either, so he gets Resource Policy Contributor on the RG only, to assign the two tag policies (section 8.4). Key Vault Secrets Officer lets him create and read secrets but not change who has access to the vault. In SQL he has no user of his own yet: he connects as `gpadmin`, the server admin login, with the password from Key Vault. That is more than the planned `db_datareader` + `db_datawriter` (point 1 below). In Fabric he is workspace Admin, because the workspace creator becomes Admin and `deploy_fabric.ps1` never demotes the signed-in creator. This is more than the design gave him (Member). In production the Admin persona would create the workspace and the Engineer would be Contributor.
- Analyst. Reader on the RG shows resource names and settings but no data. Reader gives no Key Vault data role, so `az keyvault secret show` should return 403 Forbidden for Omar; this is the negative test of PLAN T8.2, not run yet. He has no SQL user. The design is that he sees the gold tables only through the semantic model `sm_gridpulse` and the report `rpt_gridpulse`. Neither is built yet, and as workspace Viewer he may reach more than gold (point 2 below).

How the matrix was applied on 2026-11-23: the RG roles were assigned by Nacir, the subscription Owner, at 19:25 to 19:26 UTC (`az role assignment create`; the Entra object ids of Hamza and Omar are kept in the git-ignored `infra/local.settings.json`, template `infra/local.settings.example.json`). The workspace roles were set from Hamza's account once the workspace existed: Omar by `deploy_fabric.ps1 -AssignRoles`, Nacir with `fab acl set` afterwards. Output in `docs/evidence/rbac.md`.

Two ordering constraints in the scripts:

- `infra/azure/deploy.ps1` creates the vault in RBAC mode and then writes `sql-gpadmin-password` and `customer-hash-salt` in the same run. Creating a vault does not give the creator data-plane rights, so whoever runs it needs Key Vault Secrets Officer at RG scope before the first run. On 2026-11-23 the script ran under Nacir's session, so Nacir got that role first. Otherwise the script stops at step 2 and has to be re-run after the role is added.
- `deploy.ps1` creates the SQL server without tags and tags it in a second call. Once the deny policies of section 8.4 are assigned, that create would be refused. Run `deploy.ps1` before `policy_assignments.ps1`, or pass the tags at creation.

### Non-human identities

| Identity | Used by | Credential | Rights it needs | Weak point and production fix |
|---|---|---|---|---|
| Fabric connection `con_sql_gridpulse` | copy activity of `pl_daily_ingest` (ForEach over the 3 SQL tables) | SQL login `gpadmin`; `infra/fabric/deploy_fabric.ps1` reads the password from Key Vault and passes it to the connection through a temp file deleted right after (Fabric then stores it encrypted) | read 3 tables | it is the server admin login. Production: a contained read-only user, or Entra authentication with a service principal or the workspace identity, with `db_datareader` only |
| Notebook identity | `nb_silver` reading `customer-hash-salt` with `notebookutils.credentials.getSecret` | the identity the notebook runs as (the user for an interactive run; for a scheduled pipeline run, to verify in T4.1) | read one secret | today Secrets Officer covers it. Production: Key Vault Secrets User scoped to that one secret |
| `DefaultAzureCredential` on the laptop | `realtime/simulator.py` reading `es-meters-conn` | the signed-in `az` CLI user | read one secret | the simulator runs as a person. Production: the simulator would be a cloud service with a managed identity |
| Eventstream custom endpoint key | simulator sending events | SAS key inside the connection string | send to one endpoint | key in Key Vault only. Production: rotate it, or use Entra authentication if the endpoint supports it for our case |
| Outlook connection `con_outlook_alerts` | failure mail of the pipeline | OAuth of the member who created it (UI step, T3.6) | send mail | mails leave from a personal mailbox. Production: a shared mailbox or a Teams/webhook channel |

### What we have not solved (and say so in the defence)

1. Key Vault Secrets Officer lets the Engineer read `sql-gpadmin-password`, so in practice he can log in as SQL server admin. We accept it for the build because he loads the schema. Production: only the Admin reads that secret; the Engineer gets a contained user with DDL rights on his own schema.
2. One Lakehouse (DESIGN D6) means a workspace role covers bronze, silver and gold at once. `bronze_customers` holds PII in the same Lakehouse as the gold tables. To verify in T8.2: can a workspace Viewer query `bronze_customers` through the Lakehouse SQL analytics endpoint? If yes, we fix it in one of two ways: (a) remove Omar's workspace role and share only `rpt_gridpulse` and `sm_gridpulse` with him, the semantic model reading the tables with a fixed identity (a cloud connection owned by the Engineer), or (b) `DENY SELECT` on the `bronze_` and `silver_` tables for the Analyst on the SQL analytics endpoint. Three Lakehouses (one per layer) would make this a workspace or item permission question instead; we kept one for setup time and document the trade-off.
3. The Admin's Owner role comes from the subscription and also covers Nacir's other resource groups (`TP6`, `tp1`). We cannot narrow it.

## 8.2 Secrets and keys

| Secret in `kv-hz2611-cdda` | What it is | Written by | Read by, and how |
|---|---|---|---|
| `sql-gpadmin-password` | password of the SQL admin login `gpadmin` | `infra/azure/deploy.ps1`: generated once (28 characters, all four SQL complexity classes, .NET cryptographic RNG), passed to `az keyvault secret set` through a temporary file so it never appears on a command line, never printed, file deleted | `scripts/load_sql.py --kv-url ... --kv-secret sql-gpadmin-password` with `DefaultAzureCredential` (never from the command line, a file or an environment variable); `infra/fabric/deploy_fabric.ps1` when it creates `con_sql_gridpulse` (temp file, deleted at once) |
| `customer-hash-salt` | random salt for the customer pseudonym (section 8.3) | `infra/azure/deploy.ps1`: 32 random bytes as hex, generated once and kept on reruns (a new salt would change every `customer_hash`), written through a temporary file | `nb_silver` through `gridpulse.lakehouse.get_secret`, which calls `notebookutils.credentials.getSecret(key_vault_url, name)` inside Fabric |
| `es-meters-conn` | connection string of the Eventstream custom endpoint (Event Hubs protocol, includes a SAS key) | the Engineer copies it from the Eventstream source details into `az keyvault secret set` (UI step, PLAN T6.2); it is never pasted into chat or files | `realtime/simulator.py --kv-url https://kv-hz2611-cdda.vault.azure.net --kv-secret es-meters-conn` through `SecretClient` with `DefaultAzureCredential` |

Nothing secret is in Git:

- The notebooks carry only the vault URL and the secret name as parameters (`key_vault_url`, `salt_secret_name`).
- `.gitignore` excludes `.env`, `*.env`, `*.local.json` (connection ids), `data/lakehouse/` (it holds the local salt file `local_salt.txt`), `mlruns/` and `data/raw/`.
- Local runs never touch Key Vault: `scripts/run_local.py` takes the salt from `$GRIDPULSE_HASH_SALT` or generates a random one into the git-ignored `data/lakehouse/local_salt.txt`.
- `tests/unit/test_repo_hygiene.py::test_no_secret_looking_values_tracked` reads every file git tracks or would track and fails the test suite if it finds `SharedAccessKey=...`, `AccountKey=...`, a quoted `password = '...'` of 8 or more characters, or a GitHub token (`github_pat_...`). It runs with every `pytest` run.

Vault settings (`deploy.ps1`): RBAC authorization, soft delete 7 days (the minimum), purge protection off so the vault can be purged at cleanup, public network access enabled. Production: purge protection on, private endpoint, public access off.

Rotation: the SQL password and the Eventstream key can be replaced in Key Vault and in the one place that uses each. Changing the salt changes every `customer_hash`; this stays consistent because `nb_silver` recomputes all silver tables from bronze on each run and `nb_gold` rebuilds the dimensions after it.

## 8.3 Data classification

The customer data is synthetic (Faker, seed 2611, `example.com` emails, `555-01xx` phone numbers), but we handle it as if it were real.

| Column | Where | Classification | Handling |
|---|---|---|---|
| `customers.full_name` | Azure SQL | Confidential - GDPR, Name, rank HIGH | stays in SQL and `bronze_customers`; dropped in silver |
| `customers.email` | Azure SQL | Confidential - GDPR, Contact Info, HIGH | same; also checked unique (`email_unique` DQ check) |
| `customers.phone` | Azure SQL | Confidential - GDPR, Contact Info, HIGH | same |
| `customers.street_address` | Azure SQL | Confidential - GDPR, Contact Info, HIGH | same |
| `customers.postal_code` | Azure SQL | Confidential, Contact Info, MEDIUM (quasi-identifier) | same |
| `customers.customer_id`, `meters.customer_id` | Azure SQL, bronze | internal identifier that links a meter to a person | replaced by `customer_hash` in silver |
| `meter_id` in live events | Eventhouse | internal | events carry `meter_id` and `site_id` only, no customer field |
| demand, weather | Lakehouse | public (IESO, Open-Meteo) | licence notices in `NOTICE.md`; bulk IESO files never committed |

How the PII is contained:

- SQL: `sql/001_schema.sql` adds a sensitivity classification to the five PII columns (`ADD SENSITIVITY CLASSIFICATION ... WITH (LABEL, INFORMATION_TYPE, RANK)`). They show in the portal under Data Discovery and Classification and in `sys.sensitivity_classifications`. Applied on 2026-11-23: `load_sql.py --schema` printed the five classifications (`docs/evidence/azure_foundation.md`, section 3). `[TODO after T2.2: portal screenshot]`. If SQL auditing were enabled, queries touching these columns would be marked with the sensitivity information in the audit log; auditing is off (log cost), production would turn it on.
- Lakehouse: `bronze_customers` is the only table with PII (pipeline copy of `dbo.customers`). `nb_silver` writes `silver_customers_pseudo` with `customer_hash`, city, segment and `customer_since`, and `silver_meters` with the same `customer_hash` instead of `customer_id`. Gold has no PII column; `gold_dim_meter` keeps `customer_hash`, segment and `customer_since`.
- Quality gate: the DQ check `pii_absent` fails the silver run if any PII column name appears in `silver_customers_pseudo` or `silver_meters`. It passed in the local run of 2026-11-22 and in the Fabric runs of 2026-11-23 (`docs/evidence/fabric_batch.md`, section 6).
- The pseudonym is `sha2(salt || ':' || customer_id, 256)`. A plain hash of an id between 1 and 50 could be reversed by trying all 50 values; the salt kept in Key Vault prevents that, and the hash stays stable so joins between meters and customers still work. This is pseudonymisation, not anonymisation: the Admin, with the salt and SQL access, can re-identify a customer, and with only 50 customers the combination city + segment + `customer_since` can single someone out. Improvements: an HMAC with a key, and dropping `customer_since` from gold.

How Microsoft Purview would discover and classify these assets:

1. Azure SQL. Register `sql-hz2611-cdda` in the Purview Data Map, give the Purview managed identity read access to the database, and run a scan with the system scan rule set. The built-in classifiers look at column names and sampled values (email address, person name, phone number, address) and attach classifications to the columns; the results show in the catalog with the asset's schema.
2. OneLake. Register the Fabric tenant as a source and scan it. This gives the workspace items, Lakehouse tables and lineage from pipeline to Lakehouse to semantic model to report. It needs a Fabric administrator to allow read-only admin APIs for the scanner. How much column-level classification a scan gives for Lakehouse tables is to be checked against the Purview documentation before the final report.
3. Inside Fabric, without a Purview account: the OneLake catalog "Govern" view (formerly the Purview hub) lists our items with their descriptions, endorsement and sensitivity label coverage. If the UIR tenant publishes Purview Information Protection labels to us, we put "Confidential" on `lh_gridpulse` and `sm_gridpulse`; the label then follows exports to Excel or PBIX.

What a trial tenant lets us show, and what not:

| Can show | Cannot show |
|---|---|
| SQL sensitivity classifications (portal + query) | a Purview Data Map scan: we have no Purview account (the `Microsoft.Purview` provider is not registered on the subscription) and the account would add cost |
| OneLake catalog Govern view for our own items, item descriptions, Fabric lineage view of the workspace | a scan of the Fabric tenant: needs Fabric administrator rights, which none of us has (`fab api admin/tenantsettings` returns 403) |
| the `pii_absent` check and the absence of PII columns in silver and gold | sensitivity labels, unless the tenant has published them to us (to check in the label picker, T8.6) |

## 8.4 Policy and location

- Allowed regions (inherited). The subscription carries the assignment `sys.regionrestriction` ("Allowed resource deployment regions"): switzerlandnorth, italynorth, denmarkeast, germanywestcentral, polandcentral. We use Germany West Central for every Azure resource (DESIGN D21) and the Fabric trial capacity we use is in the same region. Azure Policy does not govern the Fabric trial region (the trial is not an Azure resource); its owner chose it when starting the trial.
- Required tags (ours). `infra/azure/policy_assignments.ps1` assigns the built-in definition "Require a tag on resources" (`871b6d14-10aa-478d-b590-94f262ecfa99`, effect deny) twice at RG scope: `require-tag-project` and `require-tag-owner`. The script first checks that the definition's display name is the expected one, and skips assignments that already exist. Our resources carry `project=cdda-gridpulse`, `owner=hamza.ziouine`, `course=CDDA-2627` (`infra/azure/common.ps1`). The RG itself is already tagged; this definition applies to resources inside it.
- Live denial demo: `powershell -File infra\azure\policy_assignments.ps1 -Test` tries to create the storage account `stgpulsepolicytest` without tags. Expected result: `RequestDisallowedByPolicy`, nothing created. A new assignment can take up to about 30 minutes to take effect; if the account does get created in that window, the script deletes it. Run on 2026-11-23 under Nacir's session: refused as expected (`docs/evidence/azure_foundation.md`, section 2).
- The compliance view (`az policy state summarize`) needs the `Microsoft.PolicyInsights` provider, registered on 2026-11-23 under Nacir's session.
- Production: a "modify" policy that copies tags from the RG instead of denying, "Azure SQL should disable public network access", "Key Vault should use private link", assignments at management-group level, and the policy definitions kept in the repository.

## 8.5 Encryption and networking

At rest:

- Azure SQL Database: Transparent Data Encryption is on by default with a service-managed key.
- Fabric: OneLake data (Lakehouse files and Delta tables) and Eventhouse data are encrypted at rest with Microsoft-managed keys.
- Key Vault encrypts secrets by design.
- Production option: customer-managed keys (TDE with a key in Key Vault; for Fabric, check which SKUs support workspace customer-managed keys).

In transit:

- Azure SQL: minimum TLS version 1.2, set by `deploy.ps1` (`--minimal-tls-version 1.2`).
- Fabric, Power BI, Key Vault, IESO (`https://reports-public.ieso.ca`) and Open-Meteo: HTTPS.
- Simulator to Eventstream: the Event Hubs client library uses AMQP over TLS.

Network exposure, and why it stays public here:

| Endpoint | Exposure in our build | Why | Production |
|---|---|---|---|
| `sql-hz2611-cdda` | public endpoint; firewall rules `AllowAzureServices` (0.0.0.0) and `laptop-<user>` (the current public IP of the laptop running `deploy.ps1`) | the Fabric copy activity runs on shared Fabric infrastructure with no fixed outbound IP we could allow. `AllowAzureServices` is broad: it lets any Azure-hosted client reach the login step (authentication is still required) | private endpoint, public access off, and a VNet data gateway or Fabric managed private endpoint for the pipeline (both need paid capacity, a VNet and admin rights we do not have); Entra-only authentication on SQL |
| `kv-hz2611-cdda` | public network access enabled; Entra ID authentication + RBAC | the laptop simulator and Fabric notebooks must reach it | private endpoint + firewall, trusted services only |
| Eventstream custom endpoint | public; SAS key required | the simulator runs on a laptop outside any VNet | private network path, or a managed producer inside Azure |
| Fabric workspace, Power BI | public; Entra sign-in with MFA | trial capacity, student tenant | tenant or workspace private link, conditional access |

## 8.6 Monitoring and audit

| What happens | Where it is recorded | Alert we use or would use | Status |
|---|---|---|---|
| role assignments, resource create, change and delete, policy denials | Azure activity log (subscription, kept 90 days, no cost). Query: `az monitor activity-log list -g rg-hz2611-cdda` | production: activity-log alert on `Microsoft.Authorization/roleAssignments/write` in the RG | platform default |
| who read which secret | Key Vault `AuditEvent` logs, only once a diagnostic setting sends them to Log Analytics or storage | production: alert on a secret read by an unexpected principal | designed; not enabled because Log Analytics ingestion costs money |
| logins and queries on classified SQL columns | SQL auditing | production: alert on reads of the PII columns outside the pipeline | designed; off |
| pipeline and notebook runs, durations, failures | Fabric Monitor hub (run history) | `pl_daily_ingest` failure path: Office 365 Outlook mail, then a Fail activity so the run stays marked Failed | designed (UI step T3.6) `[TODO after T3.6: screenshot of a test failure mail]` |
| data quality | `silver_dq_results`, 21 checks per run in Fabric (17 plus 4 on the Previous Runs weather; PASS / WARN / FAIL) | a FAIL makes `nb_silver` raise after writing the results and before overwriting silver, so the pipeline fails (and sends the mail once `con_outlook_alerts` exists) | cloud, 2026-11-23: 18 PASS, 3 WARN, 0 FAIL; the stop on FAIL has not been triggered in Fabric |
| abnormal live consumption | Eventhouse `meter_readings`, KQL Q2 | Activator `act_abnormal_demand`: mail when Q2 returns rows | designed `[TODO after T6.6: alert mail screenshot]` |
| spend | Cost Management budget `budget-cdda-20usd` | mails at 50 % and 100 % of actual cost and 100 % of forecast cost, to Hamza and Nacir | in place since 2026-11-06 (spend 0.00 USD on 2026-11-06 and on 2026-11-23) |
| Fabric capacity load and throttling | Fabric Capacity Metrics app (needs the capacity admin, who is the classmate owning the trial, not one of us) | production: alert on sustained throttling | optional |
| user activity in Fabric (who opened which item) | Fabric events in the Microsoft Purview audit log | production | not available to us (needs audit admin rights) |

## 8.7 Cost and cleanup

Cost drivers and sizing are in report section 10. The list of every resource with its SKU, cost estimate, status and cleanup action, and the cleanup order, are in `docs/resource_inventory.md`. Summary: Fabric trial capacity $0, Azure SQL free offer $0 (the database pauses when the free monthly allowance is used up, it does not bill), Key Vault under $0.10 a month, expected total under $2 against a $20 budget alert. After grading, `infra/azure/cleanup.ps1` deletes `rg-hz2611-cdda` only: it refuses any other name and the protected groups `TP6` and `tp1`, and asks for the RG name to be typed back.

## 8.8 Control status

Status values: designed (written down, nothing to run yet), scripted (code exists, not run against Azure or Fabric), demonstrated locally (run on the laptop, output seen), demonstrated in cloud (run in Azure or Fabric, evidence saved). "In place in cloud" means the setting exists in Azure or Fabric and was read back, but no test has exercised it yet.

| Control | Status | Evidence |
|---|---|---|
| 3 personas, Azure RBAC on the RG | in place in cloud (Key Vault Administrator and SQL Entra admin not assigned) | `docs/evidence/rbac.md` |
| Fabric workspace roles (Admin, Member, Viewer) | in place in cloud (Hamza Admin, Nacir Member, Omar Viewer) | `docs/evidence/rbac.md` |
| Analyst denied on Key Vault (403) | designed | `[TODO after T8.2: screenshot of az keyvault secret show as Omar]` |
| Viewer cannot reach `bronze_customers` | designed, to verify | section 8.1, point 2. `[TODO after T8.2]` |
| Key Vault in RBAC mode with `sql-gpadmin-password` and `customer-hash-salt` | demonstrated in cloud (2026-11-23) | `infra/azure/deploy.ps1` steps 1, 2 and 2b; `docs/evidence/azure_foundation.md` |
| `es-meters-conn` in Key Vault | designed (manual `az keyvault secret set` after the UI copy) | PLAN T6.2, `infra/fabric/README.md` browser step 2 |
| SQL password only read from Key Vault by tools | demonstrated in cloud (2026-11-23): `load_sql.py` loaded Azure SQL that way (`docs/evidence/azure_foundation.md`, section 3) and `deploy_fabric.ps1` created `con_sql_gridpulse` that way | `scripts/load_sql.py`, `infra/fabric/deploy_fabric.ps1` |
| Simulator reads its connection string from Key Vault | scripted (dry-run mode tested locally) | `realtime/simulator.py` `connection_string()`, `tests/unit/test_simulator.py` |
| `nb_silver` reads the salt from Key Vault | demonstrated in cloud in pipeline runs started by Hamza (2026-11-23); not yet in a scheduled run | `src/gridpulse/lakehouse.py` `get_secret()`; `docs/evidence/fabric_batch.md` section 6 |
| No secrets in Git | demonstrated locally | `tests/unit/test_repo_hygiene.py` |
| SQL sensitivity classifications on 5 columns | in place in cloud (applied by `load_sql.py --schema` on 2026-11-23) | `sql/001_schema.sql`; `docs/evidence/azure_foundation.md`, section 3. `[TODO after T2.2: portal screenshot]` |
| Pseudonymisation in silver + `pii_absent` check | demonstrated in cloud | Fabric runs of 2026-11-23: `silver_customers_pseudo` 50 rows, `pii_absent` PASS (`docs/evidence/fabric_batch.md`, section 6); same result in the local run of 2026-11-22 |
| Purview scan of Azure SQL and OneLake | designed | section 8.3 |
| OneLake catalog Govern view, labels | designed | `[TODO after T8.6: screenshots]` |
| Allowed regions | in place in cloud (inherited) | `az policy assignment list` on 2026-11-06 listed `sys.regionrestriction` |
| Required tags `project` and `owner`, deny | demonstrated in cloud | `infra/azure/policy_assignments.ps1`. Done 2026-11-23: an untagged storage account was refused with `RequestDisallowedByPolicy` (`docs/evidence/azure_foundation.md`, section 2). |
| TDE, OneLake encryption at rest | platform default | nothing to deploy; screenshot of the TDE blade `[TODO after T1A.2]` |
| TLS 1.2 minimum on SQL | in place in cloud | `deploy.ps1` step 3; `docs/evidence/azure_foundation.md` |
| SQL firewall (Azure services + laptop IP) | in place in cloud (the laptop rule is named after the login that created it, `laptop-mohamed-nacir`) | `deploy.ps1` step 4 |
| Activity log | platform default | `[TODO after T8.7: az monitor activity-log output]` |
| Pipeline failure mail | designed | PLAN T3.6 |
| Data-quality gate (stop on FAIL) | demonstrated in cloud (no FAIL so far, so the stop path has not run in Fabric) | Fabric runs of 2026-11-23: 21 checks, 18 PASS, 3 WARN, 0 FAIL (`docs/evidence/fabric_batch.md`); local run of 2026-11-22: 17 checks, 14 PASS, 3 WARN, 0 FAIL |
| Activator alert on Q2 | designed | `realtime/kql/q2_anomaly.kql`, PLAN T6.6 |
| Budget alerts 50 / 100 / forecast 100 | in place in cloud | budget read back on 2026-11-06 (PLAN 1.3) |
| Guarded cleanup | scripted | `infra/azure/cleanup.ps1` |

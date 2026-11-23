# GridPulse Fabric deployment (PLAN T1F.2-T1F.6, T3.1-T3.5, T6.1). Idempotent: every item is
# checked with `fab exists` before it is created, and definitions are re-imported with -f so the
# workspace matches the repo after each run.
#
# Steps:
#   1. workspace ws_gridpulse (created on the trial capacity if missing) and, with -AssignRoles,
#      Hamza = Member, Omar = Viewer (PLAN 5.1; run that part as the Admin persona)
#   2. lakehouse lh_gridpulse, Files/bronze/{ieso,openmeteo,openmeteo_forecast,openmeteo_prevruns},
#      Files/libs + wheel
#   3. environment env_gridpulse (holidays + gridpulse wheel), published by `fab import`
#   4. notebooks nb_bronze, nb_silver, nb_gold, nb_forecast, nb_predict
#   5. connections con_ieso_http, con_openmeteo_hist, con_openmeteo_fc, con_openmeteo_prev,
#      con_sql_gridpulse
#      (SQL password read from Key Vault, passed in a temp file, deleted at once);
#      con_outlook_alerts is OAuth, created once in the UI: if it exists its id is used, otherwise
#      the pipelines are imported without the mail activity (the Fail activity still marks the run)
#   6. pipelines pl_daily_ingest and pl_backfill, ids filled in by render.py
#   7. eventhouse eh_gridpulse + table/mapping/retention (run_kql.py), empty eventstream es_meters
#   8. daily schedule of pl_daily_ingest at 13:15 UTC (08:15 EST), unless one exists
#   9. ids written to infra/fabric/ids.local.json (git-ignored), then the remaining UI steps
#
# Prerequisites: proposal sent; trial capacity started by Nacir; `fab auth login` as yourself
# (Member or Admin of the workspace); `az login` for the Key Vault read; infra/azure/deploy.ps1
# already run (SQL server, database, Key Vault).
#
#   powershell -File infra\fabric\deploy_fabric.ps1 -DryRun     # zero network calls
#   powershell -File infra\fabric\deploy_fabric.ps1 -CapacityName "Trial-2026111..." [-AssignRoles]

[CmdletBinding()]
param(
    [string]$Workspace = 'ws_gridpulse',
    [string]$CapacityName,
    [string]$AlertTo,   # default: fabric.alertTo of infra/local.settings.json
    [string]$HttpConnectionType = 'HttpServer',
    [string]$ScheduleEnd,
    [switch]$AssignRoles,
    [switch]$SkipSchedule,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$Root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $Root

$Fab = 'fab'
$UserFab = Join-Path $env:APPDATA 'Python\Python314\Scripts\fab.exe'
if (Test-Path $UserFab) { $Fab = $UserFab }
$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { $Py = 'python' }
$Uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path $Uv)) { $Uv = 'uv' }

$Lakehouse = 'lh_gridpulse'
$Environment = 'env_gridpulse'
$Notebooks = @('nb_bronze', 'nb_silver', 'nb_gold', 'nb_forecast', 'nb_predict')
$Pipelines = @('pl_daily_ingest', 'pl_backfill')
$Folders = @('Files/bronze', 'Files/bronze/ieso', 'Files/bronze/openmeteo',
             'Files/bronze/openmeteo_forecast', 'Files/bronze/openmeteo_prevruns', 'Files/libs')
# Alert addresses and persona object ids come from infra/local.settings.json (git-ignored,
# template infra/local.settings.example.json). -DryRun falls back to the template placeholders.
. "$PSScriptRoot\..\local_settings.ps1"
$GpLocal = Get-GridPulseSettings -Section fabric -AllowExample:$DryRun
if (-not $AlertTo) { $AlertTo = $GpLocal.fabric.alertTo }
$Personas = [ordered]@{}
foreach ($p in @($GpLocal.fabric.personas)) { $Personas[$p.objectId] = $p.role }   # Data Engineer = Member, Analyst = Viewer
$SqlServer = 'sql-hz2611-cdda.database.windows.net'
$SqlDatabase = 'sqldb-hz2611-gridpulse'
$SqlUser = 'gpadmin'
$KeyVault = 'kv-hz2611-cdda'
$SqlPwdSecret = 'sql-gpadmin-password'
$Az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
if (-not (Test-Path $Az)) { $Az = 'az' }
$IdsFile = if ($DryRun) { Join-Path $Root 'infra\fabric\ids.dryrun.local.json' } else { Join-Path $Root 'infra\fabric\ids.local.json' }
$FakeId = '00000000-0000-4000-8000-000000000000'

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Yellow }

function Invoke-Fab {
    # Plain function on purpose (PS 5.1): every token, including -P/-f, lands in $args.
    $flat = foreach ($a in $args) { $a }
    if ($DryRun) { Write-Host "DRYRUN fab $($flat -join ' ')" -ForegroundColor DarkGray; return '' }
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $out = (& $Fab @flat 2>&1 | Out-String) } finally { $ErrorActionPreference = $old }
    if ($LASTEXITCODE -ne 0) { throw "fab $($flat[0..2] -join ' ') failed (exit $LASTEXITCODE): $out" }
    return $out.Trim()
}

function Test-FabExists($path) {
    if ($DryRun) { Write-Host "DRYRUN fab exists $path" -ForegroundColor DarkGray; return $false }
    $out = Invoke-Fab exists $path
    return ($out -match '(^|\s)true\s*$')
}

function Get-FabId($path) {
    if ($DryRun) { return $FakeId }
    $id = (Invoke-Fab get $path -q id).Trim('"', ' ', "`r", "`n")
    if ($id -notmatch '^[0-9a-fA-F-]{36}$') { throw "could not read the id of $path (got '$id')" }
    return $id
}

function Invoke-Py {
    $flat = foreach ($a in $args) { $a }
    & $Py @flat
    if ($LASTEXITCODE -ne 0) { throw "python $($flat[0]) failed (exit $LASTEXITCODE)" }
}

function Write-Ids($ids) {
    $ids | ConvertTo-Json | Set-Content -Path $IdsFile -Encoding utf8
}

$ws = "$Workspace.Workspace"
$ids = [ordered]@{ ALERT_TO = $AlertTo }

# 1. Workspace -------------------------------------------------------------------------------
Step "Workspace $ws"
if ($DryRun) { Write-Host 'DRY RUN: nothing below talks to Fabric, Azure or any network.' -ForegroundColor Cyan }
if (-not $DryRun) { Invoke-Fab auth status | Write-Host }
if (Test-FabExists $ws) {
    Write-Host 'exists'
} else {
    if (-not $CapacityName -and -not $DryRun) { throw "workspace missing: pass -CapacityName (the trial capacity name, see 'fab ls .capacities')" }
    Invoke-Fab mkdir $ws -P "capacityName=$CapacityName" | Out-Null
    Write-Host 'created'
}
$ids.WORKSPACE_ID = Get-FabId $ws
if ($AssignRoles) {
    foreach ($oid in $Personas.Keys) {
        Invoke-Fab acl set $ws -I $oid -R $Personas[$oid] -f | Out-Null
        Write-Host "role $($Personas[$oid]) -> $oid"
    }
}

# 2. Lakehouse, folders, wheel ---------------------------------------------------------------
Step "Lakehouse $Lakehouse"
$lh = "$ws/$Lakehouse.Lakehouse"
if (Test-FabExists $lh) { Write-Host 'exists' } else { Invoke-Fab mkdir $lh | Out-Null; Write-Host 'created' }
$ids.LAKEHOUSE_ID = Get-FabId $lh
foreach ($f in $Folders) {
    if (-not (Test-FabExists "$lh/$f")) { Invoke-Fab mkdir "$lh/$f" | Out-Null; Write-Host "folder $f" }
}
Step 'Build the gridpulse wheel (local, offline)'
$old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # uv logs to stderr
try { & $Uv build --wheel --offline --out-dir dist 2>&1 | Out-Host } finally { $ErrorActionPreference = $old }
if ($LASTEXITCODE -ne 0) { throw 'wheel build failed' }
$wheel = Get-ChildItem (Join-Path $Root 'dist') -Filter 'gridpulse-*.whl' | Sort-Object LastWriteTime | Select-Object -Last 1
Write-Host "wheel: $($wheel.Name)"
Invoke-Fab cp $wheel.FullName "$lh/Files/libs/" -f | Out-Null

# 3 + 4. Environment and notebooks (first render: pipelines not imported from it) -------------
Step 'Render definitions (pass 1: environment + notebooks)'
$envPath = "$ws/$Environment.Environment"
$envExists = Test-FabExists $envPath
$ids.ENVIRONMENT_ID = if ($envExists) { Get-FabId $envPath } else { $FakeId }
foreach ($t in 'NB_BRONZE_ID', 'NB_SILVER_ID', 'NB_GOLD_ID', 'NB_FORECAST_ID', 'NB_PREDICT_ID',
               'CONN_IESO_HTTP', 'CONN_OPENMETEO_HIST', 'CONN_OPENMETEO_FC', 'CONN_OPENMETEO_PREV',
               'CONN_SQL') {
    if (-not $ids.Contains($t)) { $ids[$t] = $FakeId }
}
Write-Ids $ids
Invoke-Py infra\fabric\render.py --ids $IdsFile --wheel $wheel.FullName

Step "Environment $Environment (import + publish, a few minutes the first time)"
Invoke-Fab import $envPath -i "build\fabric\$Environment.Environment" -f | Out-Null
$ids.ENVIRONMENT_ID = Get-FabId $envPath
if (-not $envExists) {
    Write-Ids $ids  # notebooks must point at the real environment id: render again
    Invoke-Py infra\fabric\render.py --ids $IdsFile --wheel $wheel.FullName
}

Step 'Notebooks'
foreach ($nb in $Notebooks) {
    Invoke-Fab import "$ws/$nb.Notebook" -i "build\fabric\$nb.Notebook" --format .py -f | Out-Null
    $ids["$($nb.Substring(3).ToUpper().Insert(0, 'NB_'))_ID"] = Get-FabId "$ws/$nb.Notebook"
    Write-Host "$nb imported"
}

# 5. Connections -----------------------------------------------------------------------------
Step 'Connections'
function Set-HttpConnection($name, $url, $token) {
    $path = ".connections/$name.Connection"
    if (-not (Test-FabExists $path)) {
        try {
            Invoke-Fab mkdir $path -P "connectionDetails.type=$HttpConnectionType,connectionDetails.parameters.url=$url,credentialDetails.type=Anonymous,privacyLevel=Public" | Out-Null
        } catch {
            Write-Warning "creating $name failed. Connection types containing http/web in this tenant:"
            Invoke-Fab api connections/supportedConnectionTypes -q "value[?contains(type, 'Http') || contains(type, 'Web')].type" | Write-Host
            throw "rerun with -HttpConnectionType <one of the above>, or create '$name' (anonymous, $url) in Manage connections"
        }
        Write-Host "$name created"
    } else { Write-Host "$name exists" }
    $ids[$token] = Get-FabId $path
}
Set-HttpConnection 'con_ieso_http' 'https://reports-public.ieso.ca/public/Demand/' 'CONN_IESO_HTTP'
Set-HttpConnection 'con_openmeteo_hist' 'https://historical-forecast-api.open-meteo.com/' 'CONN_OPENMETEO_HIST'
Set-HttpConnection 'con_openmeteo_fc' 'https://api.open-meteo.com/' 'CONN_OPENMETEO_FC'
Set-HttpConnection 'con_openmeteo_prev' 'https://previous-runs-api.open-meteo.com/' 'CONN_OPENMETEO_PREV'

$sqlConn = '.connections/con_sql_gridpulse.Connection'
if (Test-FabExists $sqlConn) {
    Write-Host 'con_sql_gridpulse exists'
} elseif ($DryRun) {
    Write-Host "DRYRUN az keyvault secret show --vault-name $KeyVault -n $SqlPwdSecret (value kept in memory)" -ForegroundColor DarkGray
    Write-Host 'DRYRUN fab api -X post connections -i <temp file with the SQL connection body, deleted after>' -ForegroundColor DarkGray
} else {
    $pwd_ = (& $Az keyvault secret show --vault-name $KeyVault -n $SqlPwdSecret --query value -o tsv)
    if ($LASTEXITCODE -ne 0 -or -not $pwd_) { throw "cannot read $SqlPwdSecret from $KeyVault (az login? Key Vault Secrets User role?)" }
    $body = @{
        displayName = 'con_sql_gridpulse'; connectivityType = 'ShareableCloud'; privacyLevel = 'Organizational'
        connectionDetails = @{ type = 'SQL'; creationMethod = 'SQL'; parameters = @(
            @{ dataType = 'Text'; name = 'server'; value = $SqlServer },
            @{ dataType = 'Text'; name = 'database'; value = $SqlDatabase }) }
        credentialDetails = @{ singleSignOnType = 'None'; connectionEncryption = 'Encrypted'; skipTestConnection = $false
            credentials = @{ credentialType = 'Basic'; username = $SqlUser; password = $pwd_ } }
    } | ConvertTo-Json -Depth 6 -Compress
    $tmp = New-TemporaryFile
    try {
        Set-Content -Path $tmp -Value $body -Encoding ascii -NoNewline
        Invoke-Fab api -X post connections -i $tmp.FullName | Out-Null
    } finally { Remove-Item $tmp -Force; $body = $null; $pwd_ = $null }
    Write-Host 'con_sql_gridpulse created'
}
$ids.CONN_SQL = Get-FabId $sqlConn
$outlook = '.connections/con_outlook_alerts.Connection'
if (Test-FabExists $outlook) {
    $ids.CONN_OUTLOOK = Get-FabId $outlook
    Write-Host 'con_outlook_alerts found: failure mail enabled'
} else {
    if ($ids.Contains('CONN_OUTLOOK')) { $ids.Remove('CONN_OUTLOOK') }
    Write-Warning 'con_outlook_alerts not found: pipelines imported WITHOUT the failure mail (create it in the UI, rerun)'
}
if ($DryRun) { $ids.CONN_OUTLOOK = $FakeId }

# 6. Pipelines -------------------------------------------------------------------------------
Step 'Render definitions (pass 2: pipelines with every id)'
Write-Ids $ids
Invoke-Py infra\fabric\render.py --ids $IdsFile --wheel $wheel.FullName
foreach ($pl in $Pipelines) {
    Invoke-Fab import "$ws/$pl.DataPipeline" -i "build\fabric\$pl.DataPipeline" -f | Out-Null
    Write-Host "$pl imported"
}

# 7. Real-time items -------------------------------------------------------------------------
Step 'Eventhouse eh_gridpulse + KQL table, eventstream es_meters'
$eh = "$ws/eh_gridpulse.Eventhouse"
if (Test-FabExists $eh) { Write-Host 'eventhouse exists' } else { Invoke-Fab mkdir $eh | Out-Null; Write-Host 'eventhouse created' }
if ($DryRun) {
    Invoke-Py infra\fabric\run_kql.py --file realtime\kql\00_tables.kql --dry-run
} else {
    $uri = (Invoke-Fab get $eh -q properties.queryServiceUri).Trim('"', ' ')
    Invoke-Py infra\fabric\run_kql.py --cluster $uri --database eh_gridpulse --file realtime\kql\00_tables.kql
}
$es = "$ws/es_meters.Eventstream"
if (Test-FabExists $es) { Write-Host 'eventstream exists' } else { Invoke-Fab mkdir $es | Out-Null; Write-Host 'eventstream created (empty)' }

# 8. Schedule --------------------------------------------------------------------------------
if (-not $SkipSchedule) {
    Step 'Daily schedule 13:15 UTC'
    $plPath = "$ws/pl_daily_ingest.DataPipeline"
    $existing = if ($DryRun) { '' } else { Invoke-Fab job run-list $plPath --schedule }
    if ($existing -match 'True|true') {
        Write-Host 'a schedule exists already, not adding another'
    } else {
        $start = (Get-Date).ToUniversalTime().Date.AddDays(1).ToString('yyyy-MM-ddT00:00:00')
        $end = if ($ScheduleEnd) { $ScheduleEnd } else { (Get-Date).ToUniversalTime().Date.AddDays(55).ToString('yyyy-MM-ddT00:00:00') }
        Invoke-Fab job run-sch $plPath --type daily --interval 13:15 --start $start --end $end --enable | Out-Null
        Write-Host "scheduled daily 13:15 UTC from $start to $end"
    }
}

# 9. Ids and what is left for the UI -----------------------------------------------------------
Write-Ids $ids
Step "Done. Ids saved to $IdsFile"
@'
Remaining UI steps (see infra/fabric/README.md):
  a. es_meters: add source "Custom endpoint" (src_simulator) and destination "Eventhouse"
     (eh_gridpulse, table meter_readings, mapping meter_readings_json, direct ingestion);
     copy the Event Hub connection string into Key Vault:
     az keyvault secret set --vault-name kv-hz2611-cdda -n es-meters-conn --file <file>
  b. con_outlook_alerts (Office 365 Outlook, OAuth) if it did not exist, then rerun this script.
  c. Semantic model sm_gridpulse from lh_gridpulse (powerbi/semantic_model_spec.md), report
     rpt_gridpulse (powerbi/report_spec.md), Real-Time Dashboard rtd_gridpulse, Activator
     act_abnormal_demand; export their definitions to the repo afterwards.
  d. First data: fab job start ws_gridpulse.Workspace/pl_backfill.DataPipeline --wait
'@ | Write-Host

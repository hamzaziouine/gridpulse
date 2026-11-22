# GridPulse Azure foundation (PLAN T1A.2, T1A.3, T1A.6). Idempotent: re-running changes nothing.
#
# Creates in rg-hz2611-cdda (germanywestcentral):
#   1. Key Vault kv-hz2611-cdda (RBAC mode, purge protection off for student cleanup, soft delete 7 d)
#   2. SQL admin password generated once, stored ONLY in Key Vault (secret sql-gpadmin-password),
#      and the pseudonymisation salt customer-hash-salt read by nb_silver (generated once, kept)
#   3. Azure SQL logical server sql-hz2611-cdda (TLS 1.2 minimum, Entra admin optional)
#   4. Firewall: Azure services (Fabric pipelines) + the current public IP of this laptop
#   5. Database sqldb-hz2611-gridpulse on the FREE offer (serverless GP Gen5 2 vCore,
#      100k vCore-s/month, AutoPause when exhausted, so it can never bill)
#
# Prerequisites (PLAN 5.3, run by Nacir as Owner): the caller has Contributor on the RG and
# "Key Vault Secrets Officer" on the vault (or on the RG). Proposal must be SENT before running.
#
#   powershell -File infra\azure\deploy.ps1 [-EntraAdminObjectId <guid> -EntraAdminName <name>]
#   powershell -File infra\azure\deploy.ps1 -WhatIf      # prints the plan, creates nothing

[CmdletBinding()]
param(
    [string]$EntraAdminObjectId,
    [string]$EntraAdminName,
    [switch]$WhatIf
)
. "$PSScriptRoot\common.ps1"
$acct = Assert-Context
$rg = $Cfg.ResourceGroup; $loc = $Cfg.Location

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Yellow }
function Plan($msg) { if ($WhatIf) { Write-Host "WHATIF: $msg" -ForegroundColor DarkGray; return $true }; return $false }

# 0. Resource group exists (created 11-06) -----------------------------------------------------
Step "Resource group $rg"
if (-not (Test-AzExists group show -n $rg)) { throw "RG $rg missing: create it first (it carries the budget)" }

# 1. Key Vault ---------------------------------------------------------------------------------
Step "Key Vault $($Cfg.KeyVault)"
if (Test-AzExists keyvault show -n $Cfg.KeyVault -g $rg) {
    Write-Host 'exists'
} elseif (-not (Plan "create Key Vault $($Cfg.KeyVault)")) {
    Invoke-Az keyvault create -n $Cfg.KeyVault -g $rg -l $loc `
        --enable-rbac-authorization true --retention-days 7 `
        --public-network-access Enabled --tags @($Cfg.Tags) | Out-Null
    Write-Host 'created'
}

# 2. SQL admin password (generated once, never printed, never written to disk) ------------------
Step "Secret $($Cfg.SqlPwdSecret)"
$sqlPwd = $null
if (-not $WhatIf) {
    $r = Invoke-AzQuiet keyvault secret show --vault-name $Cfg.KeyVault -n $Cfg.SqlPwdSecret `
        --query value -o tsv --only-show-errors
    if ($r.ok -and $r.text) {
        $sqlPwd = $r.text; Write-Host 'exists (reused)'
    } else {
        $sqlPwd = New-StrongPassword
        # Pass the value through a temp file so it never appears in the process command line.
        $tmp = New-TemporaryFile
        try {
            Set-Content -Path $tmp -Value $sqlPwd -NoNewline -Encoding ascii
            Invoke-Az keyvault secret set --vault-name $Cfg.KeyVault -n $Cfg.SqlPwdSecret `
                --file $tmp --encoding utf-8 --content-type 'text/plain' | Out-Null
        } finally { Remove-Item $tmp -Force }
        Write-Host 'generated and stored'
    }
} else { Plan "generate password, store in $($Cfg.KeyVault)/$($Cfg.SqlPwdSecret)" | Out-Null }

# 2b. Pseudonymisation salt (DESIGN D18): generated once, never rotated by this script --------
Step "Secret $($Cfg.SaltSecret)"
if (-not $WhatIf) {
    $r = Invoke-AzQuiet keyvault secret show --vault-name $Cfg.KeyVault -n $Cfg.SaltSecret `
        --query id -o tsv --only-show-errors
    if ($r.ok -and $r.text) {
        Write-Host 'exists (kept: a new salt would change every customer_hash)'
    } else {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $salt = -join ($bytes | ForEach-Object { $_.ToString('x2') })
        $tmp = New-TemporaryFile
        try {
            Set-Content -Path $tmp -Value $salt -NoNewline -Encoding ascii
            Invoke-Az keyvault secret set --vault-name $Cfg.KeyVault -n $Cfg.SaltSecret `
                --file $tmp --encoding utf-8 --content-type 'text/plain' | Out-Null
        } finally { Remove-Item $tmp -Force; $salt = $null }
        Write-Host 'generated and stored'
    }
} else { Plan "generate a 32-byte salt, store in $($Cfg.KeyVault)/$($Cfg.SaltSecret)" | Out-Null }

# 3. SQL logical server ------------------------------------------------------------------------
Step "SQL server $($Cfg.SqlServer)"
if (Test-AzExists sql server show -n $Cfg.SqlServer -g $rg) {
    Write-Host 'exists'
} elseif (-not (Plan "create SQL server $($Cfg.SqlServer) (TLS 1.2)")) {
    Invoke-Az sql server create -n $Cfg.SqlServer -g $rg -l $loc `
        -u $Cfg.SqlAdminUser -p $sqlPwd --minimal-tls-version 1.2 | Out-Null
    Invoke-Az resource tag --ids "/subscriptions/$($Cfg.SubscriptionId)/resourceGroups/$rg/providers/Microsoft.Sql/servers/$($Cfg.SqlServer)" `
        --tags @($Cfg.Tags) | Out-Null
    Write-Host 'created'
}
if ($EntraAdminObjectId -and -not (Plan "set Entra admin $EntraAdminName")) {
    Invoke-Az sql server ad-admin create -g $rg -s $Cfg.SqlServer `
        --display-name $EntraAdminName --object-id $EntraAdminObjectId | Out-Null
    Write-Host "Entra admin = $EntraAdminName"
}

# 4. Firewall ----------------------------------------------------------------------------------
Step 'SQL firewall'
if (-not (Plan 'rules AllowAzureServices + laptop IP')) {
    Invoke-Az sql server firewall-rule create -g $rg -s $Cfg.SqlServer -n AllowAzureServices `
        --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 | Out-Null
    $ip = (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 15).Trim()
    $rule = 'laptop-' + ($acct.user.name -split '@')[0].Replace('.', '-')
    Invoke-Az sql server firewall-rule create -g $rg -s $Cfg.SqlServer -n $rule `
        --start-ip-address $ip --end-ip-address $ip | Out-Null
    Write-Host "AllowAzureServices + $rule ($ip)"
}

# 5. Database on the free offer ----------------------------------------------------------------
Step "Database $($Cfg.SqlDatabase) (free offer)"
if (Test-AzExists sql db show -n $Cfg.SqlDatabase -s $Cfg.SqlServer -g $rg) {
    Write-Host 'exists'
} elseif (-not (Plan "create free serverless database $($Cfg.SqlDatabase)")) {
    Invoke-Az sql db create -g $rg -s $Cfg.SqlServer -n $Cfg.SqlDatabase `
        --edition GeneralPurpose --family Gen5 --capacity 2 --compute-model Serverless `
        --use-free-limit true --free-limit-exhaustion-behavior AutoPause `
        --backup-storage-redundancy Local --tags @($Cfg.Tags) | Out-Null
    Write-Host 'created'
}

# Verification ---------------------------------------------------------------------------------
if (-not $WhatIf) {
    Step 'Verify'
    $db = Invoke-Az sql db show -g $rg -s $Cfg.SqlServer -n $Cfg.SqlDatabase
    if (-not $db.useFreeLimit) { throw 'database is NOT on the free offer: delete it before it bills' }
    if ($db.freeLimitExhaustionBehavior -ne 'AutoPause') { throw 'exhaustion behaviour is not AutoPause' }
    [pscustomobject]@{
        KeyVault = $Cfg.KeyVault
        SqlFqdn  = "$($Cfg.SqlServer).database.windows.net"
        Database = $db.name
        FreeTier = $db.useFreeLimit
        OnLimit  = $db.freeLimitExhaustionBehavior
        Status   = $db.status
    } | Format-List
}

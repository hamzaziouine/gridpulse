# Shared settings for the GridPulse Azure scripts (dot-source this file).
# Naming follows DESIGN D22: <type>-hz2611-<name>. Region follows D21.
$ErrorActionPreference = 'Stop'

$Az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
if (-not (Test-Path $Az)) { $Az = 'az' }

# Subscription and tenant ids live in infra/local.settings.json (git-ignored); see
# infra/local.settings.example.json. Loading throws a clear error when the file is missing.
. "$PSScriptRoot\..\local_settings.ps1"
$GpLocal = Get-GridPulseSettings -Section azure

$Cfg = [ordered]@{
    SubscriptionId = $GpLocal.azure.subscriptionId   # infra/local.settings.json (git-ignored)
    TenantId       = $GpLocal.azure.tenantId
    ResourceGroup  = 'rg-hz2611-cdda'
    Location       = 'germanywestcentral'
    KeyVault       = 'kv-hz2611-cdda'
    SqlServer      = 'sql-hz2611-cdda'
    SqlDatabase    = 'sqldb-hz2611-gridpulse'
    SqlAdminUser   = 'gpadmin'
    SqlPwdSecret   = 'sql-gpadmin-password'
    SaltSecret     = 'customer-hash-salt'      # read by nb_silver (pseudonymisation, D18)
    EventSecret    = 'es-meters-conn'          # Eventstream custom endpoint, set by hand (UI copy)
    Tags           = @('project=cdda-gridpulse', 'owner=hamza.ziouine', 'course=CDDA-2627')
    # Resource groups that belong to Nacir's other courses: never touched by any script.
    Protected      = @('TP6', 'tp1')
}

function Invoke-Az {
    # Runs az, returns parsed JSON (or $null), throws on a non-zero exit code.
    # Plain (non-advanced) function on purpose: every token, including -n/-g, lands in $args.
    $flat = foreach ($a in $args) { $a }   # unroll arrays such as --tags @(...)
    $out = & $Az @flat --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') ... failed (exit $LASTEXITCODE)" }
    if ($out) { return ($out | Out-String | ConvertFrom-Json) }
    return $null
}

function Test-AzExists {
    # True when an az 'show' command finds the resource (exit 0), false otherwise.
    $flat = foreach ($a in $args) { $a }
    # PowerShell 5.1 + ErrorActionPreference=Stop turns native stderr into a terminating error,
    # so relax it while probing; "not found" is an expected answer here.
    $old = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
    try { & $Az @flat --only-show-errors -o none 2>$null | Out-Null } finally { $ErrorActionPreference = $old }
    return ($LASTEXITCODE -eq 0)
}

function Invoke-AzQuiet {
    # Like Invoke-Az but tolerant: returns @{ ok; text } and never throws (stderr captured).
    $flat = foreach ($a in $args) { $a }
    # 'Continue', not 'SilentlyContinue': PowerShell 5.1 drops native stderr records under
    # SilentlyContinue even with 2>&1, which left the text empty (SecretNotFound was never seen).
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $text = (& $Az @flat 2>&1 | ForEach-Object { "$_" } | Out-String) } finally { $ErrorActionPreference = $old }
    return @{ ok = ($LASTEXITCODE -eq 0); text = $text.Trim() }
}

function Assert-Context {
    $acct = Invoke-Az account show
    if ($acct.id -ne $Cfg.SubscriptionId) {
        Invoke-Az account set --subscription $Cfg.SubscriptionId | Out-Null
        $acct = Invoke-Az account show
    }
    if ($acct.tenantId -ne $Cfg.TenantId) { throw "wrong tenant: $($acct.tenantId)" }
    if ($Cfg.Protected -contains $Cfg.ResourceGroup) { throw 'refusing to run against a protected RG' }
    Write-Host "Signed in as $($acct.user.name) on '$($acct.name)'" -ForegroundColor Cyan
    return $acct
}

function New-StrongPassword {
    # 28 chars, all four SQL complexity classes, cryptographic RNG. No percent sign: the password
    # goes once through az.cmd (sql server create -p), where cmd.exe would expand %NAME% pairs.
    $sets = @('ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '!#+-=?_')
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $pick = {
        param($s)
        $b = New-Object byte[] 4; $rng.GetBytes($b)
        $s[[BitConverter]::ToUInt32($b, 0) % $s.Length]
    }
    $chars = foreach ($s in $sets) { & $pick $s }
    $all = -join $sets
    $chars += 1..24 | ForEach-Object { & $pick $all }
    return -join ($chars | Sort-Object { Get-Random })
}

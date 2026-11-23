# Loads infra/local.settings.json (git-ignored): subscription id, tenant id, alert e-mail
# addresses and the Entra object ids of the workspace personas. Dot-source this file, then call
# Get-GridPulseSettings. The committed template is infra/local.settings.example.json.
#
#   Copy-Item infra\local.settings.example.json infra\local.settings.json   # then edit the copy

$GpSettingsFile = Join-Path $PSScriptRoot 'local.settings.json'
$GpSettingsExample = Join-Path $PSScriptRoot 'local.settings.example.json'
$GpGuidRe = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

function Get-GridPulseSettings {
    # -Section azure|fabric checks only what the caller needs. -AllowExample (dry runs only)
    # falls back to the committed placeholders when the local file is missing.
    param(
        [ValidateSet('azure', 'fabric')][string]$Section,
        [switch]$AllowExample
    )
    $file = $GpSettingsFile
    if (-not (Test-Path $file)) {
        if ($AllowExample) {
            Write-Host "local.settings.json missing: dry run uses the placeholders of $GpSettingsExample" -ForegroundColor DarkYellow
            $s = Get-Content -Raw -Encoding UTF8 $GpSettingsExample | ConvertFrom-Json
            # Placeholders are not valid ids; give the dry run syntactically valid fakes.
            $s.azure.subscriptionId = '00000000-0000-4000-8000-0000000000aa'
            $s.azure.tenantId = '00000000-0000-4000-8000-0000000000bb'
            $s.fabric.alertTo = 'alerts@example.com'
            $i = 0
            foreach ($p in $s.fabric.personas) { $i++; $p.objectId = ('00000000-0000-4000-8000-0000000000c{0}' -f $i) }
            return $s
        }
        throw ("infra\local.settings.json not found. Copy infra\local.settings.example.json to " +
               "infra\local.settings.json and fill in the subscription id, tenant id, alert e-mails " +
               "and persona object ids (the file is git-ignored).")
    }
    $s = Get-Content -Raw -Encoding UTF8 $file | ConvertFrom-Json
    $errors = @()
    if (-not $Section -or $Section -eq 'azure') {
        if ("$($s.azure.subscriptionId)" -notmatch $GpGuidRe) { $errors += 'azure.subscriptionId is not a GUID' }
        if ("$($s.azure.tenantId)" -notmatch $GpGuidRe) { $errors += 'azure.tenantId is not a GUID' }
    }
    if (-not $Section -or $Section -eq 'fabric') {
        $mails = "$($s.fabric.alertTo)" -split ';' | Where-Object { $_ }
        if (-not $mails -or ($mails | Where-Object { $_ -notmatch '^[^@<>\s]+@[^@<>\s]+\.[A-Za-z]{2,}$' })) {
            $errors += 'fabric.alertTo must be e-mail addresses separated by ;'
        }
        foreach ($p in @($s.fabric.personas)) {
            if ("$($p.objectId)" -notmatch $GpGuidRe) { $errors += "fabric.personas: objectId of '$($p.label)' is not a GUID" }
            if ($p.role -notin @('Admin', 'Member', 'Contributor', 'Viewer')) { $errors += "fabric.personas: bad role '$($p.role)'" }
        }
    }
    if ($errors) { throw ("infra\local.settings.json is incomplete: " + ($errors -join '; ')) }
    return $s
}

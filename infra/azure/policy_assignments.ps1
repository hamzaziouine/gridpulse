# GridPulse governance (PLAN T1A.5, DESIGN D17 aligned with PROPOSAL section 10): require the tags
# `project` and `owner` on every resource in rg-hz2611-cdda. Idempotent.
# Needs "Resource Policy Contributor" (or Owner) on the RG.
#
#   powershell -File infra\azure\policy_assignments.ps1            # assign
#   powershell -File infra\azure\policy_assignments.ps1 -Test      # + live denial test (demo evidence)

[CmdletBinding()]
param([switch]$Test)
. "$PSScriptRoot\common.ps1"
Assert-Context | Out-Null
$scope = "/subscriptions/$($Cfg.SubscriptionId)/resourceGroups/$($Cfg.ResourceGroup)"
$defName = '871b6d14-10aa-478d-b590-94f262ecfa99'   # built-in "Require a tag on resources"

$def = Invoke-Az policy definition show -n $defName
if ($def.displayName -ne 'Require a tag on resources') { throw "unexpected definition: $($def.displayName)" }

foreach ($tag in 'project', 'owner') {
    $name = "require-tag-$tag"
    if (Test-AzExists policy assignment show -n $name --scope $scope) { Write-Host "$name exists"; continue }
    $params = @{ tagName = @{ value = $tag } } | ConvertTo-Json -Compress
    $tmp = New-TemporaryFile
    try {
        Set-Content -Path $tmp -Value $params -Encoding ascii
        Invoke-Az policy assignment create -n $name --display-name "GridPulse: require tag '$tag'" `
            --policy $defName --scope $scope --params "@$tmp" | Out-Null
    } finally { Remove-Item $tmp -Force }
    Write-Host "$name assigned"
}
Invoke-Az policy assignment list --scope $scope --query "[].{name:name, display:displayName}" |
    Format-Table

if ($Test) {
    # A storage account without tags must be refused (nothing gets created). Assignments can take
    # up to ~30 min to take effect after creation.
    $acct = 'stgpulsepolicytest'
    $r = Invoke-AzQuiet storage account create -n $acct -g $Cfg.ResourceGroup -l $Cfg.Location --sku Standard_LRS
    $text = $r.text
    if ($text -match 'RequestDisallowedByPolicy') {
        Write-Host 'DENIED by policy, as expected:' -ForegroundColor Green
        ($text -split "`n" | Select-String 'RequestDisallowedByPolicy|require-tag' | Select-Object -First 3) | Write-Host
    } elseif ($r.ok) {
        Write-Warning 'NOT denied (policy not effective yet?): deleting the test account'
        & $Az storage account delete -n $acct -g $Cfg.ResourceGroup --yes | Out-Null
    } else { Write-Warning "failed for another reason:`n$text" }
}

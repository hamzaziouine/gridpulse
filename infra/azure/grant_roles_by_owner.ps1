# Run by a HUMAN (the subscription owner's session), never by an agent.
# Grants per-person roles on rg-hz2611-cdda as planned in PLAN 5.3.
# Usage: powershell -ExecutionPolicy Bypass -File infra\azure\grant_roles_by_owner.ps1
$ErrorActionPreference = 'Stop'
$env:Path += ";C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
$s = Get-Content (Join-Path $PSScriptRoot '..\local.settings.json') -Raw | ConvertFrom-Json
$sub = $s.azure.subscriptionId
$scope = "/subscriptions/$sub/resourceGroups/rg-hz2611-cdda"
$hz = ($s.fabric.personas | Where-Object role -eq 'Member').objectId
$om = ($s.fabric.personas | Where-Object role -eq 'Viewer').objectId
Write-Host "Subscription: $sub"
Write-Host "Signed-in account for this subscription:" (az account show --subscription $sub --query user.name -o tsv)
foreach ($r in 'Contributor', 'Resource Policy Contributor', 'Key Vault Secrets Officer') {
    Write-Host "Granting '$r' to Hamza ($hz)"
    az role assignment create --subscription $sub --assignee-object-id $hz --assignee-principal-type User --role $r --scope $scope --output none
}
Write-Host "Granting 'Reader' to Omar ($om)"
az role assignment create --subscription $sub --assignee-object-id $om --assignee-principal-type User --role Reader --scope $scope --output none
Write-Host "Done. Current assignments on the resource group:"
az role assignment list --subscription $sub --scope $scope --query "[].{who:principalName, role:roleDefinitionName}" -o table

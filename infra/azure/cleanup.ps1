# GridPulse cleanup (PLAN T12.2): deletes rg-hz2611-cdda and everything in it, AFTER grading only.
# Hard guards: refuses any other RG name, refuses protected RGs (TP6, tp1), asks for the RG name to
# be typed back. The Key Vault is then purged so its name can be reused.
#
#   powershell -File infra\azure\cleanup.ps1

. "$PSScriptRoot\common.ps1"
Assert-Context | Out-Null
$rg = $Cfg.ResourceGroup
if ($rg -ne 'rg-hz2611-cdda' -or $Cfg.Protected -contains $rg) { throw "refusing to delete '$rg'" }

Write-Host "About to DELETE resource group '$rg' and all its resources:" -ForegroundColor Red
& $Az resource list -g $rg --query '[].{name:name,type:type}' -o table
$answer = Read-Host "Type the resource group name to confirm"
if ($answer -ne $rg) { Write-Host 'aborted'; exit 1 }

Invoke-Az group delete -n $rg --yes | Out-Null
Invoke-AzQuiet keyvault purge -n $Cfg.KeyVault | Out-Null
Write-Host "deleted $rg. Remaining groups:"
& $Az group list --query '[].name' -o tsv

# GridPulse resource inventory (PLAN T1A.6 / T12.1): read-only. Prints a Markdown table of every
# resource in rg-hz2611-cdda, the role assignments, policy assignments and month-to-date budget.
#
#   powershell -File infra\azure\inventory.ps1 > docs\evidence\inventory.md

. "$PSScriptRoot\common.ps1"
Assert-Context | Out-Null
$rg = $Cfg.ResourceGroup
$scope = "/subscriptions/$($Cfg.SubscriptionId)/resourceGroups/$rg"

"# Azure inventory, $rg ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
''
'| Name | Type | Location | Tags |'
'|---|---|---|---|'
foreach ($r in (Invoke-Az resource list -g $rg)) {
    $tags = if ($r.tags) { ($r.tags.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ', ' } else { '' }
    "| $($r.name) | $($r.type) | $($r.location) | $tags |"
}
''
'## Role assignments'
''
'| Principal | Role | Scope |'
'|---|---|---|'
foreach ($a in (Invoke-Az role assignment list -g $rg --include-inherited)) {
    "| $($a.principalName) | $($a.roleDefinitionName) | $(($a.scope -split '/')[-1]) |"
}
''
'## Policy assignments (RG + inherited)'
''
foreach ($p in (Invoke-Az policy assignment list -g $rg --disable-scope-strict-match)) {
    "- $($p.displayName) ($($p.name))"
}
''
$b = Invoke-Az rest --method get --url "https://management.azure.com$scope/providers/Microsoft.Consumption/budgets/budget-cdda-20usd?api-version=2023-05-01"
"## Budget: $($b.properties.amount) $($b.properties.currentSpend.unit)/month, spent this month: $($b.properties.currentSpend.amount)"

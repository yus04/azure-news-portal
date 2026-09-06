<#
.SYNOPSIS
  すべてのリソースを削除します。
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$NoWait
)

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

az group show --name $env:AZURE_RESOURCE_GROUP --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Log "リソースグループが存在しません: $($env:AZURE_RESOURCE_GROUP)"
    return
}

$foundryName = $null
if (Test-Path $script:OutputsJson) {
    try { $foundryName = Get-DeploymentOutput foundryAccountName } catch { $foundryName = $null }
}

if (-not $Yes) {
    Write-Warn "リソースグループ '$($env:AZURE_RESOURCE_GROUP)' 内のすべてのリソースを削除します。"
    $confirm = Read-Host '続行するには リソースグループ名 を入力してください'
    if ($confirm -ne $env:AZURE_RESOURCE_GROUP) { Stop-WithError '入力が一致しませんでした。中止します。' }
}

Write-Log "リソースグループを削除します: $($env:AZURE_RESOURCE_GROUP)"
if ($NoWait) {
    az group delete --name $env:AZURE_RESOURCE_GROUP --yes --no-wait
    Write-Warn '--NoWait のため Foundry の purge は手動で実行してください。'
} else {
    az group delete --name $env:AZURE_RESOURCE_GROUP --yes
    if ($foundryName) {
        Write-Log "論理削除された Foundry アカウントを完全削除します: $foundryName"
        az cognitiveservices account purge `
            --name $foundryName `
            --resource-group $env:AZURE_RESOURCE_GROUP `
            --location $env:AZURE_FOUNDRY_LOCATION `
            --output none 2>$null
    }
}

Remove-Item $script:OutputsJson, $script:StateFile -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $script:RepoRoot '.dist') -Recurse -Force -ErrorAction SilentlyContinue
Write-Log '削除が完了しました。'

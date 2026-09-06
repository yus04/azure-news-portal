<#
.SYNOPSIS
  インフラ全体を検証してデプロイします。
.EXAMPLE
  ./scripts/Deploy-Infra.ps1
  ./scripts/Deploy-Infra.ps1 -ValidateOnly
#>
[CmdletBinding()]
param(
    [switch]$ValidateOnly,
    [switch]$SkipWhatIf
)

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

Write-Log 'Bicep を build します'
az bicep build --file (Join-Path $script:RepoRoot 'infra/main.bicep') --stdout | Out-Null
az bicep build-params --file (Join-Path $script:RepoRoot 'infra/main.bicepparam') --stdout | Out-Null

Confirm-ResourceGroup

Write-Log 'デプロイを検証します (validate)'
Invoke-InfraDeployment -Mode validate

if (-not $SkipWhatIf) {
    Write-Log '変更内容を確認します (what-if)'
    az deployment group what-if `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name (Get-DeploymentName) `
        --template-file (Join-Path $script:RepoRoot 'infra/main.bicep') `
        --parameters (Join-Path $script:RepoRoot 'infra/main.bicepparam') `
        --no-pretty-print | Out-Null
}

if ($ValidateOnly) {
    Write-Log '-ValidateOnly が指定されたため終了します'
    return
}

Write-Log 'インフラをデプロイします (数分かかります)'
Invoke-InfraDeployment -Mode create
Save-DeploymentOutputs

Write-Log "Function App    : $(Get-DeploymentOutput functionAppName)"
Write-Log "Storage Account : $(Get-DeploymentOutput storageAccountName)"
Write-Log "Cosmos DB       : $(Get-DeploymentOutput cosmosAccountName)"
Write-Log "Foundry         : $(Get-DeploymentOutput foundryAccountName)"
Write-Log '次の手順: ./scripts/Deploy-Functions.ps1'

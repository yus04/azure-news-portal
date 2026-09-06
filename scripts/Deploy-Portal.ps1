<#
.SYNOPSIS
  Portal のコンテナーイメージを ACR で build / push し、Container App を更新します。
#>
[CmdletBinding()]
param(
    [string]$ImageName = 'azure-news-portal',
    [string]$Tag = (Get-Date -Format 'yyyyMMddHHmmss')
)

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

$registry = Get-DeploymentOutput containerRegistryName
$loginServer = Get-DeploymentOutput containerRegistryLoginServer
$image = "$loginServer/${ImageName}:$Tag"

Write-Log "コンテナーイメージをビルドします: $image"
az acr build `
    --registry $registry `
    --image "${ImageName}:$Tag" `
    --image "${ImageName}:latest" `
    --file (Join-Path $script:RepoRoot 'portal/Dockerfile') `
    --output none `
    $script:RepoRoot
if ($LASTEXITCODE -ne 0) { Stop-WithError 'ACR ビルドに失敗しました。' }

Save-StateValue -Key 'PORTAL_IMAGE' -Value $image

Write-Log 'Container App を更新します'
Invoke-InfraDeployment -Mode create
Save-DeploymentOutputs

$portalUrl = Get-DeploymentOutput portalUrl
Write-Log "Azure News Portal: $portalUrl"

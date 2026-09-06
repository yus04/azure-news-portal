<#
.SYNOPSIS
  Function デプロイ後に Event Grid Event Subscription を作成 / 更新します。
#>
[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

$functionApp = Get-DeploymentOutput functionAppName
$functionName = Get-DeploymentOutput eventGridFunctionName

az functionapp function show `
    --resource-group $env:AZURE_RESOURCE_GROUP `
    --name $functionApp `
    --function-name $functionName --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "$functionName が見つかりません。先に Deploy-Functions.ps1 を実行してください。"
}

Save-StateValue -Key 'DEPLOY_EVENT_GRID_SUBSCRIPTION' -Value 'true'

Write-Log 'Event Grid Event Subscription をデプロイします'
Invoke-InfraDeployment -Mode create
Save-DeploymentOutputs

az eventgrid system-topic event-subscription show `
    --resource-group $env:AZURE_RESOURCE_GROUP `
    --system-topic-name (Get-DeploymentOutput eventGridSystemTopicName) `
    --name (Get-DeploymentOutput eventGridSubscriptionName) `
    --query '{name:name, provisioningState:provisioningState}' -o yaml

Write-Log '完了しました。./scripts/Upload-Samples.ps1 でサンプル記事を投入できます。'

<#
.SYNOPSIS
  インフラ → Function → Event Grid → Portal をまとめてデプロイします。
#>
[CmdletBinding()]
param([switch]$SkipWhatIf)

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

Write-Log '==== 1/4 インフラ ===='
& (Join-Path $PSScriptRoot 'Deploy-Infra.ps1') -SkipWhatIf:$SkipWhatIf

Write-Log '==== 2/4 Function コード ===='
& (Join-Path $PSScriptRoot 'Deploy-Functions.ps1')

Write-Log '==== 3/4 Event Grid Subscription ===='
& (Join-Path $PSScriptRoot 'Configure-EventGrid.ps1')

Write-Log '==== 4/4 Portal コンテナー ===='
& (Join-Path $PSScriptRoot 'Deploy-Portal.ps1')

Write-Log 'デプロイが完了しました。./scripts/Upload-Samples.ps1 でサンプル記事を投入できます。'

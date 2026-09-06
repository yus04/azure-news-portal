<#
.SYNOPSIS
  Function コードをパッケージ化して Flex Consumption の Function App へデプロイします。
#>
[CmdletBinding()]
param([string]$FunctionAppName)

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

if (-not $FunctionAppName) { $FunctionAppName = Get-DeploymentOutput functionAppName }

$buildDir = Join-Path $script:RepoRoot '.dist/functions'
$package = Join-Path $script:RepoRoot '.dist/functions.zip'

Write-Log "デプロイパッケージを作成します: $package"
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
if (Test-Path $package) { Remove-Item $package -Force }
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

Copy-Item (Join-Path $script:RepoRoot 'functions/function_app.py') $buildDir
Copy-Item (Join-Path $script:RepoRoot 'functions/host.json') $buildDir
Copy-Item (Join-Path $script:RepoRoot 'functions/requirements.txt') $buildDir
Copy-Item (Join-Path $script:RepoRoot 'functions/src') (Join-Path $buildDir 'src') -Recurse
Copy-Item (Join-Path $script:RepoRoot 'shared/newsportal_shared') (Join-Path $buildDir 'newsportal_shared') -Recurse

Get-ChildItem $buildDir -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $buildDir '*') -DestinationPath $package -Force

Write-Log "Function App へデプロイします: $FunctionAppName"
az functionapp deploy `
    --resource-group $env:AZURE_RESOURCE_GROUP `
    --name $FunctionAppName `
    --src-path $package `
    --type zip `
    --output none

if ($LASTEXITCODE -ne 0) {
    Write-Warn "'az functionapp deploy' が失敗しました。config-zip でリトライします。"
    az functionapp deployment source config-zip `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name $FunctionAppName `
        --src $package `
        --output none
}

Write-Log '関数の登録を確認します (最大 10 分)'
for ($attempt = 1; $attempt -le 30; $attempt++) {
    az functionapp function show `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name $FunctionAppName `
        --function-name ProcessArticleBlob --output none 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Log 'ProcessArticleBlob を検出しました'
        return
    }
    Start-Sleep -Seconds 20
}

Write-Warn 'ProcessArticleBlob をまだ検出できません。Application Insights のログを確認してください。'
exit 1

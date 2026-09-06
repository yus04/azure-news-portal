<#
.SYNOPSIS
  入力コンテナーの Blob を再アップロードして再処理をトリガーします。
.EXAMPLE
  ./scripts/Reprocess.ps1 -Prefix articles/2026/08
  ./scripts/Reprocess.ps1 -Failed
  ./scripts/Reprocess.ps1 -All -DryRun
#>
[CmdletBinding()]
param(
    [string]$Prefix,
    [string]$Blob,
    [switch]$Failed,
    [switch]$All,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'Common.ps1')

if (-not ($Prefix -or $Blob -or $Failed -or $All)) {
    Stop-WithError '-Prefix / -Blob / -Failed / -All のいずれかを指定してください。'
}

Initialize-Deployment

$account = Get-DeploymentOutput storageAccountName
$container = Get-DeploymentOutput inputContainerName
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $temp -Force | Out-Null

try {
    $blobs = @()
    if ($Blob) {
        $blobs = @($Blob)
    } elseif ($Failed) {
        $blobs = az cosmosdb sql container query `
            --account-name (Get-DeploymentOutput cosmosAccountName) `
            --resource-group $env:AZURE_RESOURCE_GROUP `
            --database-name (Get-DeploymentOutput cosmosDatabaseName) `
            --name (Get-DeploymentOutput cosmosArticlesContainerName) `
            --query-text "SELECT VALUE c.rawBlobPath FROM c WHERE c.processingStatus = 'failed'" `
            -o tsv | ForEach-Object { $_ -replace "^$container/", '' }
    } else {
        $blobs = az storage blob list `
            --account-name $account --container-name $container `
            --prefix $Prefix --auth-mode login `
            --query "[?ends_with(name, '.json')].name" -o tsv
    }

    $count = 0
    foreach ($name in $blobs) {
        if (-not $name) { continue }
        $count++
        if ($DryRun) {
            Write-Host "  (dry-run) $name"
            continue
        }
        $local = Join-Path $temp ($name -replace '[\\/]', '_')
        Write-Log "再処理: $name"
        az storage blob download --account-name $account --container-name $container `
            --name $name --file $local --auth-mode login --output none
        az storage blob upload --account-name $account --container-name $container `
            --name $name --file $local --content-type 'application/json' `
            --overwrite true --auth-mode login --output none
    }

    Write-Log "対象 $count 件を処理しました (DryRun=$DryRun)"
}
finally {
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}

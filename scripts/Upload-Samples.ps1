<#
.SYNOPSIS
  サンプル記事 JSON を入力コンテナーへアップロードします。
#>
[CmdletBinding()]
param(
    [string[]]$Path,
    [string]$Prefix = 'articles'
)

. (Join-Path $PSScriptRoot 'Common.ps1')

Initialize-Deployment

$account = Get-DeploymentOutput storageAccountName
$container = Get-DeploymentOutput inputContainerName
$sampleRoot = Join-Path $script:RepoRoot 'samples/articles'

$files = if ($Path) {
    $Path | ForEach-Object { Get-Item $_ }
} else {
    Get-ChildItem $sampleRoot -Recurse -Filter '*.json'
}

foreach ($file in $files) {
    $relative = $file.FullName.Substring($sampleRoot.Length).TrimStart('\', '/').Replace('\', '/')
    $blob = "$Prefix/$relative"
    Write-Log "アップロード: $blob"
    az storage blob upload `
        --account-name $account `
        --container-name $container `
        --name $blob `
        --file $file.FullName `
        --content-type 'application/json' `
        --overwrite true `
        --auth-mode login `
        --output none
}

Write-Log 'アップロードが完了しました。'

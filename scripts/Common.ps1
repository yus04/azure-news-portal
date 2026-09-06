# 各 PowerShell スクリプトが読み込む共通関数。

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:StateFile = Join-Path $script:RepoRoot '.deploy-outputs.env'
$script:OutputsJson = Join-Path $script:RepoRoot 'azure-outputs.json'

function Write-Log {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message) -ForegroundColor Cyan
}

function Write-Warn {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Stop-WithError {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[error] $Message" -ForegroundColor Red
    exit 1
}

function Initialize-Deployment {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Stop-WithError 'Azure CLI (az) が見つかりません。'
    }

    $envFile = Join-Path $script:RepoRoot '.env'
    if (Test-Path $envFile) {
        Get-Content $envFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
            $pair = $_ -split '=', 2
            [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim())
        }
    }

    if (Test-Path $script:StateFile) {
        Get-Content $script:StateFile | Where-Object { $_ -match '=' } | ForEach-Object {
            $pair = $_ -split '=', 2
            [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim())
        }
    }

    if (-not $env:AZURE_ENV_NAME) { $env:AZURE_ENV_NAME = 'dev' }
    if (-not $env:AZURE_NAME_PREFIX) { $env:AZURE_NAME_PREFIX = 'newsportal' }
    if (-not $env:AZURE_LOCATION) { $env:AZURE_LOCATION = 'japaneast' }
    if (-not $env:AZURE_FOUNDRY_LOCATION) { $env:AZURE_FOUNDRY_LOCATION = 'eastus2' }
    if (-not $env:AZURE_RESOURCE_GROUP) {
        $env:AZURE_RESOURCE_GROUP = "rg-$($env:AZURE_NAME_PREFIX)-$($env:AZURE_ENV_NAME)"
    }
    if (-not $env:PORTAL_IMAGE) { $env:PORTAL_IMAGE = '' }
    if (-not $env:DEPLOY_EVENT_GRID_SUBSCRIPTION) { $env:DEPLOY_EVENT_GRID_SUBSCRIPTION = 'false' }

    az account show --output none 2>$null
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Azure にログインしていません。'az login' を実行してください。" }

    if ($env:AZURE_SUBSCRIPTION_ID) {
        az account set --subscription $env:AZURE_SUBSCRIPTION_ID
    }

    az bicep version --output none 2>$null
    if ($LASTEXITCODE -ne 0) { az bicep install }

    Write-Log "リソースグループ: $($env:AZURE_RESOURCE_GROUP)"
}

function Save-StateValue {
    param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][AllowEmptyString()][string]$Value)

    $lines = @()
    if (Test-Path $script:StateFile) {
        $lines = Get-Content $script:StateFile | Where-Object { $_ -notmatch "^$Key=" }
    }
    $lines += "$Key=$Value"
    Set-Content -Path $script:StateFile -Value $lines -Encoding utf8
    [Environment]::SetEnvironmentVariable($Key, $Value)
}

function Get-DeploymentName {
    "newsportal-$($env:AZURE_ENV_NAME)"
}

function Confirm-ResourceGroup {
    az group show --name $env:AZURE_RESOURCE_GROUP --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "リソースグループを作成します: $($env:AZURE_RESOURCE_GROUP)"
        az group create --name $env:AZURE_RESOURCE_GROUP --location $env:AZURE_LOCATION --output none
    }
}

function Invoke-InfraDeployment {
    param([ValidateSet('create', 'validate')][string]$Mode = 'create')

    Write-Log "Bicep デプロイ ($Mode): PORTAL_IMAGE='$($env:PORTAL_IMAGE)' EVENT_GRID='$($env:DEPLOY_EVENT_GRID_SUBSCRIPTION)'"
    az deployment group $Mode `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name (Get-DeploymentName) `
        --template-file (Join-Path $script:RepoRoot 'infra/main.bicep') `
        --parameters (Join-Path $script:RepoRoot 'infra/main.bicepparam') `
        --output none
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Bicep デプロイに失敗しました。' }
}

function Save-DeploymentOutputs {
    az deployment group show `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name (Get-DeploymentName) `
        --query properties.outputs -o json | Set-Content -Path $script:OutputsJson -Encoding utf8
    Write-Log "デプロイ出力を保存しました: $script:OutputsJson"
}

function Get-DeploymentOutput {
    param([Parameter(Mandatory)][string]$Name)

    if (-not (Test-Path $script:OutputsJson)) {
        Stop-WithError 'azure-outputs.json がありません。先に Deploy-Infra.ps1 を実行してください。'
    }
    $outputs = Get-Content $script:OutputsJson -Raw | ConvertFrom-Json
    if (-not $outputs.PSObject.Properties.Name.Contains($Name)) {
        Stop-WithError "出力 '$Name' が見つかりません。"
    }
    $outputs.$Name.value
}

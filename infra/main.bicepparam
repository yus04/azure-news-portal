using './main.bicep'

// ---------------------------------------------------------------------------
// 開発環境 (dev) 用パラメーター
// 環境変数で上書きできる値は readEnvironmentVariable() を使用しています。
// ---------------------------------------------------------------------------

param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'dev')
param namePrefix = readEnvironmentVariable('AZURE_NAME_PREFIX', 'newsportal')
param location = readEnvironmentVariable('AZURE_LOCATION', 'japaneast')

// Foundry のモデル提供リージョンに合わせて変更してください。
// gpt-5.6-luna の提供状況は README の「モデルのリージョンとクォータ確認」を参照。
param foundryLocation = readEnvironmentVariable('AZURE_FOUNDRY_LOCATION', 'eastus2')

param tags = {
  environment: readEnvironmentVariable('AZURE_ENV_NAME', 'dev')
  workload: 'azure-news-portal'
  SecurityControl: 'Ignore'
}

// --- Functions -------------------------------------------------------------
param functionsPythonVersion = '3.11'
param functionsInstanceMemoryMB = 2048
param functionsMaximumInstanceCount = 40

// --- Microsoft Foundry -----------------------------------------------------
param foundryModelName = readEnvironmentVariable('FOUNDRY_MODEL_NAME', 'gpt-5.6-luna')
param foundryModelVersion = readEnvironmentVariable('FOUNDRY_MODEL_VERSION', '')
param foundryDeploymentName = readEnvironmentVariable('FOUNDRY_DEPLOYMENT_NAME', 'gpt-5-6-luna')
param foundryDeploymentSkuName = readEnvironmentVariable('FOUNDRY_DEPLOYMENT_SKU', 'GlobalStandard')
param foundryDeploymentCapacity = int(readEnvironmentVariable('FOUNDRY_DEPLOYMENT_CAPACITY', '50'))
param foundryApiVersion = readEnvironmentVariable('FOUNDRY_API_VERSION', '2025-04-01-preview')
param foundryApiStyle = readEnvironmentVariable('FOUNDRY_API_STYLE', 'chat')
param foundryReasoningEffort = readEnvironmentVariable('FOUNDRY_REASONING_EFFORT', 'low')
param foundryMaxOutputTokens = 4000

// --- Portal ----------------------------------------------------------------
// 空の場合はプレースホルダーイメージでデプロイし、scripts/deploy-portal.sh で差し替えます。
param portalImage = readEnvironmentVariable('PORTAL_IMAGE', '')
param portalMinReplicas = 0
param portalMaxReplicas = 5

// --- デプロイフェーズ -------------------------------------------------------
// Function コードのデプロイ後に true にして再デプロイします。
param deployEventGridSubscription = bool(readEnvironmentVariable('DEPLOY_EVENT_GRID_SUBSCRIPTION', 'false'))

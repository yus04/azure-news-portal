metadata description = 'Azure News Portal - Azure 記事の取り込み・要約パイプラインと Web ポータルの全リソースを構築します。'

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// 共通パラメーター
// ---------------------------------------------------------------------------

@description('環境識別子。リソース名に使用します (例: dev / stg / prod)。')
@minLength(2)
@maxLength(8)
param environmentName string = 'dev'

@description('リソース名の接頭辞。英小文字と数字のみ推奨。')
@minLength(3)
@maxLength(12)
param namePrefix string = 'newsportal'

@description('リソースのデプロイ先リージョン。')
param location string = resourceGroup().location

@description('Microsoft Foundry (AI Services) のデプロイ先リージョン。モデル提供状況に合わせて変更します。')
param foundryLocation string = location

@description('全リソースに付与するタグ。')
param tags object = {}

@description('リソース名の一意化トークン。既定はリソースグループから決定的に生成されます。')
@maxLength(13)
param resourceToken string = toLower(uniqueString(subscription().id, resourceGroup().name, environmentName))

// ---------------------------------------------------------------------------
// Storage / コンテナー名
// ---------------------------------------------------------------------------

@description('入力記事 JSON を保存する Blob コンテナー名。Event Grid の監視対象です。')
param inputContainerName string = 'raw-articles'

@description('処理済み画像を保存する Blob コンテナー名。')
param imagesContainerName string = 'article-images'

@description('元記事の抽出本文/HTML アーカイブを保存する Blob コンテナー名。')
param contentArchiveContainerName string = 'article-content'

@description('Event Grid のデッドレター出力先 Blob コンテナー名。')
param deadLetterContainerName string = 'eventgrid-deadletter'

@description('Azure Functions (Flex Consumption) のデプロイパッケージ用 Blob コンテナー名。')
param functionReleasesContainerName string = 'function-releases'

@description('処理に失敗した記事のスナップショットを保存する Blob コンテナー名。')
param failedContainerName string = 'failed-articles'

// ---------------------------------------------------------------------------
// Functions
// ---------------------------------------------------------------------------

@description('Azure Functions の Python バージョン。')
@allowed(['3.10', '3.11', '3.12'])
param functionsPythonVersion string = '3.11'

@description('Flex Consumption のインスタンスメモリ (MB)。')
@allowed([2048, 4096])
param functionsInstanceMemoryMB int = 2048

@description('Flex Consumption の最大インスタンス数。')
@minValue(40)
@maxValue(1000)
param functionsMaximumInstanceCount int = 40

@description('Event Grid Trigger を持つ Function 名。Event Grid Subscription の宛先に使用します。')
param eventGridFunctionName string = 'ProcessArticleBlob'

// ---------------------------------------------------------------------------
// Microsoft Foundry
// ---------------------------------------------------------------------------

@description('Foundry モデル名。既定は gpt-5.6-luna。リージョンで提供されていない場合のみ変更してください。')
param foundryModelName string = 'gpt-5.6-luna'

@description('Foundry モデルのバージョン。空文字の場合はバージョンを指定せずにデプロイします。')
param foundryModelVersion string = ''

@description('Foundry モデルのフォーマット。')
param foundryModelFormat string = 'OpenAI'

@description('モデルデプロイ名。アプリケーションはこの名前でモデルを呼び出します。')
param foundryDeploymentName string = 'gpt-5-6-luna'

@description('モデルデプロイの SKU 名。Standard Global は GlobalStandard を指定します。')
@allowed(['GlobalStandard', 'DataZoneStandard', 'Standard', 'GlobalProvisionedManaged', 'ProvisionedManaged'])
param foundryDeploymentSkuName string = 'GlobalStandard'

@description('モデルデプロイの容量 (1000 TPM 単位)。')
@minValue(1)
param foundryDeploymentCapacity int = 50

@description('推論 API バージョン。')
param foundryApiVersion string = '2025-04-01-preview'

@description('推論 API のスタイル。chat = Chat Completions / responses = Responses API。')
@allowed(['chat', 'responses'])
param foundryApiStyle string = 'chat'

@description('reasoning effort。対応モデルのみ有効。空文字で無効化。')
@allowed(['', 'minimal', 'low', 'medium', 'high'])
param foundryReasoningEffort string = 'low'

@description('モデルの最大出力トークン数。')
@minValue(256)
param foundryMaxOutputTokens int = 4000

@description('Foundry 呼び出しのタイムアウト秒数。')
@minValue(10)
param foundryTimeoutSeconds int = 120

@description('Foundry 呼び出しの最大リトライ回数。')
@minValue(0)
@maxValue(10)
param foundryMaxRetries int = 3

@description('コンテンツフィルター (RAI) ポリシー名。')
param foundryRaiPolicyName string = 'Microsoft.DefaultV2'

// ---------------------------------------------------------------------------
// Cosmos DB
// ---------------------------------------------------------------------------

@description('Cosmos DB データベース名。')
param cosmosDatabaseName string = 'newsportal'

@description('記事コンテナー名。')
param cosmosArticlesContainerName string = 'articles'

@description('処理状態コンテナー名。')
param cosmosStateContainerName string = 'processing-state'

// ---------------------------------------------------------------------------
// Portal (Container Apps)
// ---------------------------------------------------------------------------

@description('Portal コンテナーイメージ。空の場合はプレースホルダーイメージでデプロイし、後続スクリプトで差し替えます。')
param portalImage string = ''

@description('Portal の最小レプリカ数。0 でスケールゼロ。')
@minValue(0)
param portalMinReplicas int = 0

@description('Portal の最大レプリカ数。')
@minValue(1)
param portalMaxReplicas int = 5

@description('Portal コンテナーの待ち受けポート。')
param portalTargetPort int = 8000

// ---------------------------------------------------------------------------
// デプロイフェーズ制御
// ---------------------------------------------------------------------------

@description('Event Grid Event Subscription を作成するかどうか。Function コードのデプロイ後に true でデプロイします。')
param deployEventGridSubscription bool = false

@description('記事処理ロジックのバージョン。値を変更すると全記事が再処理対象になります。')
param processingVersion string = '1.0.0'

// ---------------------------------------------------------------------------
// 変数
// ---------------------------------------------------------------------------

var shortPrefix = take(replace(toLower(namePrefix), '-', ''), 8)
var baseName = '${namePrefix}-${environmentName}'

var defaultTags = union(
  {
    'azd-env-name': environmentName
    application: 'azure-news-portal'
  },
  tags
)

var names = {
  logAnalytics: 'log-${baseName}-${resourceToken}'
  appInsights: 'appi-${baseName}-${resourceToken}'
  storage: 'st${shortPrefix}${resourceToken}'
  functionPlan: 'plan-func-${baseName}-${resourceToken}'
  functionApp: 'func-${baseName}-${resourceToken}'
  systemTopic: 'evgt-${baseName}-${resourceToken}'
  eventSubscription: 'evgs-articles'
  foundry: 'aif-${baseName}-${resourceToken}'
  foundryProject: 'proj-${baseName}'
  cosmos: 'cosmos-${baseName}-${resourceToken}'
  registry: 'cr${shortPrefix}${resourceToken}'
  containerAppsEnv: 'cae-${baseName}-${resourceToken}'
  portalApp: 'ca-portal-${baseName}'
  functionIdentity: 'id-func-${baseName}-${resourceToken}'
  portalIdentity: 'id-portal-${baseName}-${resourceToken}'
  eventGridDeadLetterIdentity: 'id-egdl-${baseName}-${resourceToken}'
}

// ---------------------------------------------------------------------------
// Managed Identity (ユーザー割り当て)
// ---------------------------------------------------------------------------

resource functionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.functionIdentity
  location: location
  tags: defaultTags
}

resource portalIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.portalIdentity
  location: location
  tags: defaultTags
}

resource eventGridDeadLetterIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.eventGridDeadLetterIdentity
  location: location
  tags: defaultTags
}

// ---------------------------------------------------------------------------
// モジュール
// ---------------------------------------------------------------------------

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    logAnalyticsName: names.logAnalytics
    appInsightsName: names.appInsights
    location: location
    tags: defaultTags
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    storageAccountName: names.storage
    location: location
    tags: defaultTags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    containerNames: [
      inputContainerName
      imagesContainerName
      contentArchiveContainerName
      deadLetterContainerName
      functionReleasesContainerName
      failedContainerName
    ]
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    accountName: names.foundry
    projectName: names.foundryProject
    location: foundryLocation
    tags: defaultTags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    modelName: foundryModelName
    modelVersion: foundryModelVersion
    modelFormat: foundryModelFormat
    deploymentName: foundryDeploymentName
    skuName: foundryDeploymentSkuName
    capacity: foundryDeploymentCapacity
    raiPolicyName: foundryRaiPolicyName
  }
}

module cosmos 'modules/cosmos-db.bicep' = {
  name: 'cosmos-db'
  params: {
    accountName: names.cosmos
    location: location
    tags: defaultTags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    databaseName: cosmosDatabaseName
    articlesContainerName: cosmosArticlesContainerName
    stateContainerName: cosmosStateContainerName
  }
}

module registry 'modules/container-registry.bicep' = {
  name: 'container-registry'
  params: {
    registryName: names.registry
    location: location
    tags: defaultTags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
  }
}

module functions 'modules/functions.bicep' = {
  name: 'functions'
  params: {
    planName: names.functionPlan
    functionAppName: names.functionApp
    location: location
    tags: defaultTags
    identityResourceId: functionIdentity.id
    identityClientId: functionIdentity.properties.clientId
    storageAccountName: storage.outputs.storageAccountName
    storageBlobEndpoint: storage.outputs.blobEndpoint
    deploymentContainerName: functionReleasesContainerName
    pythonVersion: functionsPythonVersion
    instanceMemoryMB: functionsInstanceMemoryMB
    maximumInstanceCount: functionsMaximumInstanceCount
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    appSettings: {
      AZURE_CLIENT_ID: functionIdentity.properties.clientId
      STORAGE_ACCOUNT_NAME: storage.outputs.storageAccountName
      STORAGE_BLOB_ENDPOINT: storage.outputs.blobEndpoint
      INPUT_CONTAINER_NAME: inputContainerName
      IMAGES_CONTAINER_NAME: imagesContainerName
      CONTENT_ARCHIVE_CONTAINER_NAME: contentArchiveContainerName
      FAILED_CONTAINER_NAME: failedContainerName
      COSMOS_ENDPOINT: cosmos.outputs.documentEndpoint
      COSMOS_DATABASE_NAME: cosmosDatabaseName
      COSMOS_ARTICLES_CONTAINER: cosmosArticlesContainerName
      COSMOS_STATE_CONTAINER: cosmosStateContainerName
      FOUNDRY_ENDPOINT: foundry.outputs.endpoint
      FOUNDRY_PROJECT_ENDPOINT: foundry.outputs.projectEndpoint
      FOUNDRY_MODEL_DEPLOYMENT: foundryDeploymentName
      FOUNDRY_API_VERSION: foundryApiVersion
      FOUNDRY_API_STYLE: foundryApiStyle
      FOUNDRY_REASONING_EFFORT: foundryReasoningEffort
      FOUNDRY_MAX_OUTPUT_TOKENS: string(foundryMaxOutputTokens)
      FOUNDRY_TIMEOUT_SECONDS: string(foundryTimeoutSeconds)
      FOUNDRY_MAX_RETRIES: string(foundryMaxRetries)
      PROCESSING_VERSION: processingVersion
      PYTHON_ENABLE_INIT_INDEXING: '1'
    }
  }
}

module containerApps 'modules/container-apps.bicep' = {
  name: 'container-apps'
  params: {
    environmentName: names.containerAppsEnv
    containerAppName: names.portalApp
    location: location
    tags: defaultTags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    identityResourceId: portalIdentity.id
    identityClientId: portalIdentity.properties.clientId
    registryLoginServer: registry.outputs.loginServer
    image: portalImage
    minReplicas: portalMinReplicas
    maxReplicas: portalMaxReplicas
    targetPort: portalTargetPort
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    environmentVariables: {
      AZURE_CLIENT_ID: portalIdentity.properties.clientId
      COSMOS_ENDPOINT: cosmos.outputs.documentEndpoint
      COSMOS_DATABASE_NAME: cosmosDatabaseName
      COSMOS_ARTICLES_CONTAINER: cosmosArticlesContainerName
      STORAGE_BLOB_ENDPOINT: storage.outputs.blobEndpoint
      IMAGES_CONTAINER_NAME: imagesContainerName
      PORTAL_ENVIRONMENT: environmentName
    }
  }
  dependsOn: [
    roleAssignments
  ]
}

module roleAssignments 'modules/role-assignments.bicep' = {
  name: 'role-assignments'
  params: {
    functionPrincipalId: functionIdentity.properties.principalId
    portalPrincipalId: portalIdentity.properties.principalId
    storageAccountName: storage.outputs.storageAccountName
    functionReleasesContainerName: functionReleasesContainerName
    imagesContainerName: imagesContainerName
    foundryAccountName: foundry.outputs.accountName
    registryName: registry.outputs.registryName
    cosmosAccountName: cosmos.outputs.accountName
    cosmosDatabaseName: cosmosDatabaseName
    cosmosArticlesContainerName: cosmosArticlesContainerName
    cosmosStateContainerName: cosmosStateContainerName
    eventGridDeadLetterPrincipalId: eventGridDeadLetterIdentity.properties.principalId
  }
}

// Event Grid: システムトピックは常に作成し、Event Subscription は Function デプロイ後に作成する。
module eventGrid 'modules/event-grid.bicep' = {
  name: 'event-grid'
  params: {
    systemTopicName: names.systemTopic
    eventSubscriptionName: names.eventSubscription
    location: location
    tags: defaultTags
    storageAccountName: storage.outputs.storageAccountName
    inputContainerName: inputContainerName
    deadLetterContainerName: deadLetterContainerName
    functionAppName: functions.outputs.functionAppName
    functionName: eventGridFunctionName
    deadLetterIdentityResourceId: eventGridDeadLetterIdentity.id
    deploySubscription: deployEventGridSubscription
  }
  dependsOn: [
    roleAssignments
  ]
}

// ---------------------------------------------------------------------------
// 出力
// ---------------------------------------------------------------------------

output resourceGroupName string = resourceGroup().name
output location string = location
output storageAccountName string = storage.outputs.storageAccountName
output storageBlobEndpoint string = storage.outputs.blobEndpoint
output inputContainerName string = inputContainerName
output imagesContainerName string = imagesContainerName
output functionAppName string = functions.outputs.functionAppName
output functionAppHostName string = functions.outputs.defaultHostName
output eventGridFunctionName string = eventGridFunctionName
output eventGridSystemTopicName string = names.systemTopic
output eventGridSubscriptionName string = names.eventSubscription
output cosmosAccountName string = cosmos.outputs.accountName
output cosmosEndpoint string = cosmos.outputs.documentEndpoint
output cosmosDatabaseName string = cosmosDatabaseName
output cosmosArticlesContainerName string = cosmosArticlesContainerName
output cosmosStateContainerName string = cosmosStateContainerName
output foundryAccountName string = foundry.outputs.accountName
output foundryEndpoint string = foundry.outputs.endpoint
output foundryProjectEndpoint string = foundry.outputs.projectEndpoint
output foundryDeploymentName string = foundryDeploymentName
output containerRegistryName string = registry.outputs.registryName
output containerRegistryLoginServer string = registry.outputs.loginServer
output containerAppsEnvironmentName string = containerApps.outputs.environmentName
output portalContainerAppName string = containerApps.outputs.containerAppName
output portalUrl string = containerApps.outputs.fqdn == '' ? '' : 'https://${containerApps.outputs.fqdn}'
output functionIdentityClientId string = functionIdentity.properties.clientId
output portalIdentityClientId string = portalIdentity.properties.clientId
output applicationInsightsName string = monitoring.outputs.appInsightsName
output logAnalyticsWorkspaceName string = monitoring.outputs.logAnalyticsWorkspaceName

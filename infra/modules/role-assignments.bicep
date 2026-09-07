metadata description = 'Function / Portal のマネージド ID に対する最小権限のロール割り当てを作成します。'

@description('Azure Functions のマネージド ID のプリンシパル ID。')
param functionPrincipalId string

@description('Azure News Portal (Container App) のマネージド ID のプリンシパル ID。')
param portalPrincipalId string

@description('Event Grid のデッドレター書き込み用マネージド ID のプリンシパル ID。')
param eventGridDeadLetterPrincipalId string

param storageAccountName string
param functionReleasesContainerName string
param imagesContainerName string

param foundryAccountName string
param registryName string

param cosmosAccountName string
param cosmosDatabaseName string
param cosmosArticlesContainerName string
param cosmosStateContainerName string

// 組み込みロール定義 ID
var roles = {
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  monitoringMetricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  cognitiveServicesOpenAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
}

// Cosmos DB 組み込みデータプレーンロール
var cosmosDataReaderRoleId = '00000000-0000-0000-0000-000000000001'
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource releasesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  name: '${storageAccountName}/default/${functionReleasesContainerName}'
}

resource imagesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  name: '${storageAccountName}/default/${imagesContainerName}'
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: registryName
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

// ---------------------------------------------------------------------------
// Azure Functions
// ---------------------------------------------------------------------------

// Functions ホストランタイム (azure-webjobs-hosts / azure-webjobs-secrets) および
// 記事 Blob の読み書きに必要。ホストはコンテナー作成を行うためアカウントスコープが必須。
resource funcBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionPrincipalId, roles.storageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Flex Consumption のデプロイコンテナーには Blob Data Owner が必要。
resource funcDeploymentOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(releasesContainer.id, functionPrincipalId, roles.storageBlobDataOwner)
  scope: releasesContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource eventGridDeadLetterContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, eventGridDeadLetterPrincipalId, roles.storageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalId: eventGridDeadLetterPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource funcQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionPrincipalId, roles.storageQueueDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageQueueDataContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource funcTableContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionPrincipalId, roles.storageTableDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageTableDataContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource funcFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, functionPrincipalId, roles.cognitiveServicesOpenAiUser)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roles.cognitiveServicesOpenAiUser
    )
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource funcCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, functionPrincipalId, roles.cognitiveServicesUser)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Application Insights へのテレメトリ送信 (Entra ID 認証を使用する場合に必要)。
resource funcMetricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, functionPrincipalId, roles.monitoringMetricsPublisher)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roles.monitoringMetricsPublisher
    )
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource funcCosmosArticles 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, functionPrincipalId, cosmosDataContributorRoleId, cosmosArticlesContainerName)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: functionPrincipalId
    scope: '${cosmosAccount.id}/dbs/${cosmosDatabaseName}/colls/${cosmosArticlesContainerName}'
  }
}

resource funcCosmosState 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, functionPrincipalId, cosmosDataContributorRoleId, cosmosStateContainerName)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: functionPrincipalId
    scope: '${cosmosAccount.id}/dbs/${cosmosDatabaseName}/colls/${cosmosStateContainerName}'
  }
  dependsOn: [
    funcCosmosArticles
  ]
}

// ---------------------------------------------------------------------------
// Azure News Portal
// ---------------------------------------------------------------------------

resource portalImagesReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(imagesContainer.id, portalPrincipalId, roles.storageBlobDataReader)
  scope: imagesContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
    principalId: portalPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource portalAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, portalPrincipalId, roles.acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: portalPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource portalMetricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, portalPrincipalId, roles.monitoringMetricsPublisher)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roles.monitoringMetricsPublisher
    )
    principalId: portalPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource portalCosmosReader 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, portalPrincipalId, cosmosDataReaderRoleId, cosmosArticlesContainerName)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataReaderRoleId}'
    principalId: portalPrincipalId
    scope: '${cosmosAccount.id}/dbs/${cosmosDatabaseName}/colls/${cosmosArticlesContainerName}'
  }
  dependsOn: [
    funcCosmosState
  ]
}

output functionRoleAssignmentIds array = [
  funcBlobContributor.id
  funcDeploymentOwner.id
  eventGridDeadLetterContributor.id
  funcQueueContributor.id
  funcTableContributor.id
  funcFoundryUser.id
  funcCognitiveUser.id
  funcMetricsPublisher.id
  funcCosmosArticles.id
  funcCosmosState.id
]

output portalRoleAssignmentIds array = [
  portalImagesReader.id
  portalAcrPull.id
  portalMetricsPublisher.id
  portalCosmosReader.id
]

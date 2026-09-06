metadata description = 'Azure Cosmos DB for NoSQL (Serverless) アカウント、データベース、コンテナーを作成します。キー認証は無効化します。'

param accountName string
param location string
param tags object = {}
param logAnalyticsWorkspaceId string

param databaseName string
param articlesContainerName string
param stateContainerName string

@description('処理状態ドキュメントの TTL (秒)。既定は 30 日。')
param stateTtlSeconds int = 2592000

@description('キー / リソーストークン認証を無効化するかどうか。')
param disableLocalAuth bool = true

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: accountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: disableLocalAuth
    disableKeyBasedMetadataWriteAccess: true
    enableAutomaticFailover: false
    enableFreeTier: false
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: 'Enabled'
    defaultIdentity: 'FirstPartyIdentity'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource articlesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: articlesContainerName
  properties: {
    resource: {
      id: articlesContainerName
      partitionKey: {
        paths: [
          '/partitionKey'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/partitionKey/?' }
          { path: '/publishedAt/?' }
          { path: '/processedAt/?' }
          { path: '/ingestedAt/?' }
          { path: '/category/?' }
          { path: '/importance/?' }
          { path: '/importanceRank/?' }
          { path: '/updateType/?' }
          { path: '/source/?' }
          { path: '/sourceCategory/?' }
          { path: '/processingStatus/?' }
          { path: '/contentHash/?' }
          { path: '/processingVersion/?' }
          { path: '/products/[]/?' }
          { path: '/terms/[]/?' }
          { path: '/tags/[]/?' }
          { path: '/searchKeywords/[]/?' }
        ]
        excludedPaths: [
          { path: '/*' }
          { path: '/"_etag"/?' }
        ]
        compositeIndexes: [
          [
            { path: '/processingStatus', order: 'ascending' }
            { path: '/publishedAt', order: 'descending' }
          ]
          [
            { path: '/category', order: 'ascending' }
            { path: '/publishedAt', order: 'descending' }
          ]
          [
            { path: '/importance', order: 'ascending' }
            { path: '/publishedAt', order: 'descending' }
          ]
          [
            { path: '/source', order: 'ascending' }
            { path: '/publishedAt', order: 'descending' }
          ]
        ]
      }
    }
  }
}

resource stateContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: stateContainerName
  properties: {
    resource: {
      id: stateContainerName
      defaultTtl: stateTtlSeconds
      partitionKey: {
        paths: [
          '/articleId'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/articleId/?' }
          { path: '/eventId/?' }
          { path: '/status/?' }
          { path: '/updatedAt/?' }
        ]
        excludedPaths: [
          { path: '/*' }
          { path: '/"_etag"/?' }
        ]
      }
    }
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-cosmos'
  scope: account
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'DataPlaneRequests'
        enabled: true
      }
      {
        category: 'ControlPlaneRequests'
        enabled: true
      }
      {
        category: 'QueryRuntimeStatistics'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Requests'
        enabled: true
      }
    ]
  }
}

output accountName string = account.name
output accountId string = account.id
output documentEndpoint string = account.properties.documentEndpoint
output databaseName string = database.name
output articlesContainerName string = articlesContainer.name
output stateContainerName string = stateContainer.name

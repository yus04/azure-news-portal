metadata description = 'Flex Consumption プランと Linux Python Function App を作成します。認証はすべて Managed Identity を使用します。'

param planName string
param functionAppName string
param location string
param tags object = {}

@description('Function App に割り当てるユーザー割り当てマネージド ID のリソース ID。')
param identityResourceId string

@description('ユーザー割り当てマネージド ID のクライアント ID。')
param identityClientId string

param storageAccountName string
param storageBlobEndpoint string
param deploymentContainerName string

@allowed(['3.10', '3.11', '3.12'])
param pythonVersion string = '3.11'

@allowed([2048, 4096])
param instanceMemoryMB int = 2048

@minValue(40)
param maximumInstanceCount int = 40

param logAnalyticsWorkspaceId string
param appInsightsConnectionString string

@description('追加のアプリケーション設定 (キー/値のオブジェクト)。')
param appSettings object = {}

var baseAppSettings = {
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
  APPLICATIONINSIGHTS_AUTHENTICATION_STRING: 'ClientId=${identityClientId};Authorization=AAD'
  AzureWebJobsStorage__accountName: storageAccountName
  AzureWebJobsStorage__blobServiceUri: storageBlobEndpoint
  AzureWebJobsStorage__queueServiceUri: replace(storageBlobEndpoint, '.blob.', '.queue.')
  AzureWebJobsStorage__tableServiceUri: replace(storageBlobEndpoint, '.blob.', '.table.')
  AzureWebJobsStorage__credential: 'managedidentity'
  AzureWebJobsStorage__clientId: identityClientId
}

var mergedSettings = union(baseAppSettings, appSettings)

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityResourceId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    publicNetworkAccess: 'Enabled'
    keyVaultReferenceIdentity: identityResourceId
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageBlobEndpoint}${deploymentContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: identityResourceId
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: instanceMemoryMB
        maximumInstanceCount: maximumInstanceCount
      }
      runtime: {
        name: 'python'
        version: pythonVersion
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'FtpsOnly'
      http20Enabled: true
      appSettings: [
        for setting in items(mergedSettings): {
          name: setting.key
          value: setting.value
        }
      ]
      cors: {
        allowedOrigins: []
        supportCredentials: false
      }
    }
  }
}

resource ftpPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: functionApp
  name: 'ftp'
  properties: {
    allow: false
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-functionapp'
  scope: functionApp
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'FunctionAppLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output defaultHostName string = functionApp.properties.defaultHostName
output planName string = plan.name

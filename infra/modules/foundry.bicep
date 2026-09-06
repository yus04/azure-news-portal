metadata description = 'Microsoft Foundry (AI Services) アカウント、プロジェクト、モデルデプロイを作成します。ローカル認証 (API キー) は無効化します。'

param accountName string
param projectName string
param location string
param tags object = {}
param logAnalyticsWorkspaceId string

param modelName string
param modelVersion string = ''
param modelFormat string = 'OpenAI'
param deploymentName string
param skuName string = 'GlobalStandard'
param capacity int = 50
param raiPolicyName string = 'Microsoft.DefaultV2'

@description('API キー (ローカル認証) を無効化するかどうか。Managed Identity のみを使用します。')
param disableLocalAuth bool = true

var modelDefinition = union(
  {
    format: modelFormat
    name: modelName
  },
  empty(modelVersion) ? {} : { version: modelVersion }
)

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: disableLocalAuth
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Azure News Portal'
    description: 'Azure News Portal の記事要約に使用する Foundry プロジェクト'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: deploymentName
  sku: {
    name: skuName
    capacity: capacity
  }
  properties: {
    model: modelDefinition
    raiPolicyName: raiPolicyName
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-foundry'
  scope: account
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'Audit'
        enabled: true
      }
      {
        category: 'RequestResponse'
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

output accountName string = account.name
output accountId string = account.id
output endpoint string = account.properties.endpoint
output projectName string = project.name
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output deploymentName string = modelDeployment.name

metadata description = 'Container Apps Environment と Azure News Portal の Container App を作成します。ACR からの取得は Managed Identity を使用します。'

param environmentName string
param containerAppName string
param location string
param tags object = {}

param logAnalyticsWorkspaceId string

@description('Container App に割り当てるユーザー割り当てマネージド ID のリソース ID。')
param identityResourceId string

@description('ユーザー割り当てマネージド ID のクライアント ID。')
param identityClientId string

@description('ACR のログインサーバー (例: crxxxx.azurecr.io)。')
param registryLoginServer string

@description('デプロイするコンテナーイメージ。空の場合はプレースホルダーを使用します。')
param image string = ''

@minValue(0)
param minReplicas int = 0

@minValue(1)
param maxReplicas int = 5

param targetPort int = 8000

param appInsightsConnectionString string

@description('コンテナーに設定する環境変数 (キー/値のオブジェクト)。')
param environmentVariables object = {}

@description('CPU コア数。')
param cpu string = '0.5'

@description('メモリサイズ。')
param memory string = '1Gi'

var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var placeholderPort = 80
var effectiveImage = empty(image) ? placeholderImage : image
var usingPlaceholder = empty(image)
var effectivePort = usingPlaceholder ? placeholderPort : targetPort

var mergedEnv = union(
  {
    APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
    PORT: string(targetPort)
  },
  environmentVariables
)

var envArray = [
  for item in items(mergedEnv): {
    name: item.key
    value: item.value
  }
]

var probeArray = [
  {
    type: 'Liveness'
    httpGet: {
      path: '/healthz'
      port: targetPort
    }
    initialDelaySeconds: 5
    periodSeconds: 30
    failureThreshold: 3
  }
  {
    type: 'Readiness'
    httpGet: {
      path: '/readyz'
      port: targetPort
    }
    initialDelaySeconds: 3
    periodSeconds: 10
    failureThreshold: 6
  }
]

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    zoneRedundant: false
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource environmentDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-container-apps-env'
  scope: managedEnvironment
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'portal' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityResourceId}': {}
    }
  }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 2
      ingress: {
        external: true
        targetPort: effectivePort
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: usingPlaceholder
        ? []
        : [
            {
              server: registryLoginServer
              identity: identityResourceId
            }
          ]
    }
    template: {
      containers: [
        {
          name: 'portal'
          image: effectiveImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: usingPlaceholder ? [] : envArray
          probes: usingPlaceholder ? [] : probeArray
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '30'
              }
            }
          }
        ]
      }
    }
  }
}

output environmentName string = managedEnvironment.name
output environmentId string = managedEnvironment.id
output containerAppName string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output identityClientIdUsed string = identityClientId

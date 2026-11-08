metadata description = 'Attaches an existing Function App to a pre-provisioned VNet integration subnet.'

targetScope = 'resourceGroup'

param functionAppName string
param functionIntegrationSubnetId string

resource functionApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionAppName
}

resource functionVnetIntegration 'Microsoft.Web/sites/networkConfig@2025-03-01' = {
  parent: functionApp
  kind: 'functionapp'
  name: 'virtualNetwork'
  properties: {
    subnetResourceId: functionIntegrationSubnetId
    swiftSupported: true
  }
}

output functionIntegrationSubnetId string = functionIntegrationSubnetId

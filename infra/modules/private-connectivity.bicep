metadata description = 'GitHub Actions OIDC identity, Cosmos DB Private Link, and Functions VNet integration.'

param location string
param enablePrivateNetworking bool = false

param ingestionIdentityName string
param feedIdentityName string
param storageAccountName string
param inputContainerName string = 'raw-articles'

param cosmosAccountName string
param cosmosResourceGroupName string = resourceGroup().name
param cosmosPrivateEndpointName string

param functionAppName string
param functionAppResourceGroupName string = resourceGroup().name

param virtualNetworkName string = ''
param virtualNetworkResourceGroupName string = resourceGroup().name
param privateEndpointSubnetId string = ''
param functionIntegrationSubnetId string = ''
param privateDnsVnetLinkName string = ''

var githubIssuer = 'https://token.actions.githubusercontent.com'
var githubAudience = 'api://AzureADTokenExchange'
var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var privateDnsZoneName = 'privatelink.documents.azure.com'

resource ingestionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: ingestionIdentityName
  location: location
}

resource feedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: feedIdentityName
  location: location
}

resource ingestionFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = {
  parent: ingestionIdentity
  name: 'azure-news-ingest-main'
  properties: {
    issuer: githubIssuer
    subject: 'repo:yus04/azure-news-ingest:ref:refs/heads/main'
    audiences: [
      githubAudience
    ]
  }
}

resource feedFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = {
  parent: feedIdentity
  name: 'azurenewsfeed-master'
  properties: {
    issuer: githubIssuer
    subject: 'repo:yus04/azurenewsfeed:ref:refs/heads/master'
    audiences: [
      githubAudience
    ]
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource inputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blobService
  name: inputContainerName
}

resource ingestionBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(inputContainer.id, ingestionIdentity.id, blobDataContributorRoleId)
  scope: inputContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: ingestionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource feedBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(inputContainer.id, feedIdentity.id, blobDataContributorRoleId)
  scope: inputContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: feedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
  scope: resourceGroup(cosmosResourceGroupName)
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: empty(virtualNetworkName) ? 'not-configured' : virtualNetworkName
  scope: resourceGroup(virtualNetworkResourceGroupName)
}

resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enablePrivateNetworking) {
  name: cosmosPrivateEndpointName
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${cosmosPrivateEndpointName}-connection'
        properties: {
          privateLinkServiceId: cosmosAccount.id
          groupIds: [
            'Sql'
          ]
        }
      }
    ]
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enablePrivateNetworking) {
  name: privateDnsZoneName
  location: 'global'
}

resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (enablePrivateNetworking) {
  parent: cosmosPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cosmos-sql'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

resource privateDnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enablePrivateNetworking) {
  parent: privateDnsZone
  name: privateDnsVnetLinkName
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

module functionVnetIntegration 'function-vnet-integration.bicep' = if (enablePrivateNetworking) {
  name: 'function-vnet-integration'
  scope: resourceGroup(functionAppResourceGroupName)
  params: {
    functionAppName: functionAppName
    functionIntegrationSubnetId: functionIntegrationSubnetId
  }
}

output ingestionIdentityName string = ingestionIdentity.name
output ingestionIdentityResourceId string = ingestionIdentity.id
output ingestionIdentityClientId string = ingestionIdentity.properties.clientId
output ingestionIdentityPrincipalId string = ingestionIdentity.properties.principalId
output ingestionFederatedSubject string = ingestionFederation.properties.subject
output feedIdentityName string = feedIdentity.name
output feedIdentityResourceId string = feedIdentity.id
output feedIdentityClientId string = feedIdentity.properties.clientId
output feedIdentityPrincipalId string = feedIdentity.properties.principalId
output feedFederatedSubject string = feedFederation.properties.subject
output storageAccountName string = storageAccount.name
output inputContainerName string = inputContainer.name
output cosmosPrivateEndpointId string = enablePrivateNetworking ? cosmosPrivateEndpoint.id : ''
output cosmosPrivateDnsZoneId string = enablePrivateNetworking ? privateDnsZone.id : ''
output privateDnsVnetLinkId string = enablePrivateNetworking ? privateDnsVnetLink.id : ''
output functionIntegrationSubnetId string = enablePrivateNetworking ? functionIntegrationSubnetId : ''

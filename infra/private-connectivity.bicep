metadata description = 'Adds GitHub Actions OIDC, Cosmos DB Private Link, and Functions VNet integration to an existing deployment.'

targetScope = 'resourceGroup'

@description('Resource deployment region; must match the Functions app and VNet region.')
param location string

@description('Environment label used to derive default ingestion identity names.')
@minLength(2)
@maxLength(8)
param environmentName string = 'dev'

@description('Resource name prefix used to derive default ingestion identity names.')
@minLength(3)
@maxLength(12)
param namePrefix string = 'newsportal'

@description('Existing Storage Account name.')
param storageAccountName string

@description('Existing Cosmos DB for NoSQL account name.')
param cosmosAccountName string

@description('Resource group containing the existing Cosmos DB account.')
param cosmosResourceGroupName string = resourceGroup().name

@description('Resource group for the Cosmos Private Endpoint.')
param cosmosPrivateEndpointResourceGroupName string = resourceGroup().name

@description('Existing Azure Functions app name.')
param functionAppName string

@description('Resource group containing the existing Functions app.')
param functionAppResourceGroupName string = resourceGroup().name

@description('Existing VNet name.')
param virtualNetworkName string

@description('Resource group containing the existing VNet.')
param virtualNetworkResourceGroupName string = resourceGroup().name

@description('Resource ID of an existing subnet dedicated to Private Endpoints.')
param privateEndpointSubnetId string

@description('Resource ID of an existing Flex Consumption integration subnet delegated to Microsoft.App/environments.')
param functionIntegrationSubnetId string

@description('Private Endpoint name. Defaults to a deterministic Cosmos-account-specific name.')
param cosmosPrivateEndpointName string = 'pe-${cosmosAccountName}-sql'

@description('Private DNS VNet link name.')
param privateDnsVnetLinkName string = 'link-${virtualNetworkName}'

@description('Resource group containing the Cosmos private DNS zone.')
param privateDnsZoneResourceGroupName string = resourceGroup().name

@description('Cosmos DB for NoSQL private DNS zone name.')
param privateDnsZoneName string = 'privatelink.documents.azure.com'

@description('Use an existing private DNS zone instead of creating it.')
param createPrivateDnsZone bool = true

@description('Create the VNet link. Set false only when the named link already exists and should be left untouched.')
param createPrivateDnsVnetLink bool = true

@description('Create a Cosmos Private Endpoint. Set false to reuse the existing endpoint with cosmosPrivateEndpointName.')
param createCosmosPrivateEndpoint bool = true

@description('Create/update the endpoint DNS zone group. Set false if an existing zone group should be preserved.')
param configurePrivateDnsZoneGroup bool = true

@description('Existing article input Blob container.')
param inputContainerName string = 'raw-articles'

var baseName = '${namePrefix}-${environmentName}'

module connectivity 'modules/private-connectivity.bicep' = {
  name: 'private-connectivity'
  params: {
    location: location
    enablePrivateNetworking: true
    ingestionIdentityName: 'id-gh-ingest-${baseName}'
    feedIdentityName: 'id-gh-feed-${baseName}'
    storageAccountName: storageAccountName
    inputContainerName: inputContainerName
    cosmosAccountName: cosmosAccountName
    cosmosResourceGroupName: cosmosResourceGroupName
    cosmosPrivateEndpointResourceGroupName: cosmosPrivateEndpointResourceGroupName
    cosmosPrivateEndpointName: cosmosPrivateEndpointName
    createCosmosPrivateEndpoint: createCosmosPrivateEndpoint
    configurePrivateDnsZoneGroup: configurePrivateDnsZoneGroup
    privateDnsZoneResourceGroupName: privateDnsZoneResourceGroupName
    privateDnsZoneName: privateDnsZoneName
    createPrivateDnsZone: createPrivateDnsZone
    createPrivateDnsVnetLink: createPrivateDnsVnetLink
    functionAppName: functionAppName
    functionAppResourceGroupName: functionAppResourceGroupName
    virtualNetworkName: virtualNetworkName
    virtualNetworkResourceGroupName: virtualNetworkResourceGroupName
    privateEndpointSubnetId: privateEndpointSubnetId
    functionIntegrationSubnetId: functionIntegrationSubnetId
    privateDnsVnetLinkName: privateDnsVnetLinkName
  }
}

output ingestionIdentityName string = connectivity.outputs.ingestionIdentityName
output ingestionIdentityResourceId string = connectivity.outputs.ingestionIdentityResourceId
output ingestionIdentityClientId string = connectivity.outputs.ingestionIdentityClientId
output ingestionFederatedSubject string = connectivity.outputs.ingestionFederatedSubject
output feedIdentityName string = connectivity.outputs.feedIdentityName
output feedIdentityResourceId string = connectivity.outputs.feedIdentityResourceId
output feedIdentityClientId string = connectivity.outputs.feedIdentityClientId
output feedFederatedSubject string = connectivity.outputs.feedFederatedSubject
output storageAccountName string = connectivity.outputs.storageAccountName
output inputContainerName string = connectivity.outputs.inputContainerName
output cosmosPrivateEndpointId string = connectivity.outputs.cosmosPrivateEndpointId
output cosmosPrivateEndpointName string = cosmosPrivateEndpointName
output cosmosPrivateEndpointResourceGroupName string = cosmosPrivateEndpointResourceGroupName
output cosmosPrivateDnsZoneId string = connectivity.outputs.cosmosPrivateDnsZoneId
output cosmosPrivateDnsZoneName string = privateDnsZoneName
output cosmosPrivateDnsZoneGroupId string = connectivity.outputs.cosmosPrivateDnsZoneGroupId
output privateDnsVnetLinkId string = connectivity.outputs.privateDnsVnetLinkId
output privateDnsVnetLinkName string = privateDnsVnetLinkName
output functionIntegrationSubnetId string = connectivity.outputs.functionIntegrationSubnetId

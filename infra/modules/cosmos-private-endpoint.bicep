metadata description = 'Creates a Cosmos DB private endpoint in a selected resource group.'

targetScope = 'resourceGroup'

param privateEndpointName string
param location string
param cosmosAccountId string
param privateEndpointSubnetId string
param createPrivateEndpoint bool = true

resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (createPrivateEndpoint) {
  name: privateEndpointName
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${privateEndpointName}-connection'
        properties: {
          privateLinkServiceId: cosmosAccountId
          groupIds: [
            'Sql'
          ]
        }
      }
    ]
  }
}

output privateEndpointId string = resourceId('Microsoft.Network/privateEndpoints', privateEndpointName)

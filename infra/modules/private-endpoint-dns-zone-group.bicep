metadata description = 'Optionally attaches an existing Cosmos DB Private Endpoint to a private DNS zone.'

targetScope = 'resourceGroup'

param privateEndpointName string
param privateDnsZoneId string
param configurePrivateDnsZoneGroup bool = true

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' existing = {
  name: privateEndpointName
}

resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (configurePrivateDnsZoneGroup) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cosmos-sql'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output privateDnsZoneGroupId string = configurePrivateDnsZoneGroup ? privateDnsZoneGroup.id : ''

metadata description = 'Creates or reuses the Cosmos DB private DNS zone and optionally links a VNet.'

targetScope = 'resourceGroup'

param privateDnsZoneName string = 'privatelink.documents.azure.com'
param virtualNetworkId string
param privateDnsVnetLinkName string
param createPrivateDnsZone bool = true
param createPrivateDnsVnetLink bool = true

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: privateDnsZoneName
}

resource newPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (createPrivateDnsZone) {
  name: privateDnsZoneName
  location: 'global'
}

resource privateDnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (createPrivateDnsVnetLink) {
  parent: privateDnsZone
  name: privateDnsVnetLinkName
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
  dependsOn: [
    newPrivateDnsZone
  ]
}

output privateDnsZoneId string = createPrivateDnsZone ? newPrivateDnsZone.id : privateDnsZone.id
output privateDnsVnetLinkId string = createPrivateDnsVnetLink ? privateDnsVnetLink.id : ''

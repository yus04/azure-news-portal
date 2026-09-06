metadata description = 'Storage の Event Grid System Topic と、入力記事コンテナーのみを対象とした Event Subscription を作成します。'

param systemTopicName string
param eventSubscriptionName string
param location string
param tags object = {}

param storageAccountName string
param inputContainerName string
param deadLetterContainerName string

param functionAppName string
param functionName string

@description('Event Subscription を作成するかどうか。Function コードのデプロイ後に true にします。')
param deploySubscription bool = false

@description('最大配信試行回数。')
@minValue(1)
@maxValue(30)
param maxDeliveryAttempts int = 10

@description('イベントの有効期間 (分)。')
@minValue(1)
@maxValue(1440)
param eventTimeToLiveInMinutes int = 1440

@description('1 回の配信でまとめて送るイベント数の上限。')
@minValue(1)
param maxEventsPerBatch int = 1

var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource deadLetterContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  name: '${storageAccountName}/default/${deadLetterContainerName}'
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionAppName
}

resource systemTopic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: systemTopicName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    source: storageAccount.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// デッドレター書き込みはシステムトピックのマネージド ID で行う (共有キーは無効のため)。
resource deadLetterRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(deadLetterContainer.id, systemTopic.id, storageBlobDataContributorRoleId)
  scope: deadLetterContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: systemTopic.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource eventSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = if (deploySubscription) {
  parent: systemTopic
  name: eventSubscriptionName
  properties: {
    eventDeliverySchema: 'EventGridSchema'
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        resourceId: '${functionApp.id}/functions/${functionName}'
        maxEventsPerBatch: maxEventsPerBatch
        preferredBatchSizeInKilobytes: 64
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Storage.BlobCreated'
      ]
      subjectBeginsWith: '/blobServices/default/containers/${inputContainerName}/blobs/'
      subjectEndsWith: '.json'
      isSubjectCaseSensitive: false
      enableAdvancedFilteringOnArrays: true
      advancedFilters: [
        {
          operatorType: 'StringNotIn'
          key: 'data.api'
          values: [
            'CopyBlobSync'
          ]
        }
      ]
    }
    retryPolicy: {
      maxDeliveryAttempts: maxDeliveryAttempts
      eventTimeToLiveInMinutes: eventTimeToLiveInMinutes
    }
    deadLetterWithResourceIdentity: {
      identity: {
        type: 'SystemAssigned'
      }
      deadLetterDestination: {
        endpointType: 'StorageBlob'
        properties: {
          resourceId: storageAccount.id
          blobContainerName: deadLetterContainerName
        }
      }
    }
  }
  dependsOn: [
    deadLetterRoleAssignment
  ]
}

output systemTopicName string = systemTopic.name
output systemTopicId string = systemTopic.id
output eventSubscriptionDeployed bool = deploySubscription

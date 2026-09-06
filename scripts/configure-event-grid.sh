#!/usr/bin/env bash
# Function コードのデプロイ後に Event Grid Event Subscription を作成 / 更新します。

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

init

FUNCTION_APP="$(output_value functionAppName)"
FUNCTION_NAME="$(output_value eventGridFunctionName)"

log "Function の存在を確認します: ${FUNCTION_APP}/${FUNCTION_NAME}"
if ! az functionapp function show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${FUNCTION_APP}" \
      --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  fail "${FUNCTION_NAME} が見つかりません。先に ./scripts/deploy-functions.sh を実行してください。"
fi

export DEPLOY_EVENT_GRID_SUBSCRIPTION=true
save_state_value DEPLOY_EVENT_GRID_SUBSCRIPTION true

log "Event Grid Event Subscription をデプロイします"
run_infra_deployment create
capture_outputs

TOPIC="$(output_value eventGridSystemTopicName)"
SUBSCRIPTION="$(output_value eventGridSubscriptionName)"

log "Event Subscription の状態:"
az eventgrid system-topic event-subscription show \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --system-topic-name "${TOPIC}" \
  --name "${SUBSCRIPTION}" \
  --query '{name:name, provisioningState:provisioningState, filter:filter.subjectBeginsWith, deadLetter:deadLetterWithResourceIdentity.deadLetterDestination.blobContainerName}' \
  -o yaml

log "完了しました。./scripts/upload-samples.sh でサンプル記事を投入できます。"

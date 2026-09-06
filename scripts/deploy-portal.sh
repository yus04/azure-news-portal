#!/usr/bin/env bash
# Portal のコンテナーイメージを ACR で build / push し、Container App を更新します。
# ローカルの Docker は不要です (az acr build を使用)。

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

init

REGISTRY="$(output_value containerRegistryName)"
LOGIN_SERVER="$(output_value containerRegistryLoginServer)"
IMAGE_NAME="${PORTAL_IMAGE_NAME:-azure-news-portal}"
TAG="${PORTAL_IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
IMAGE="${LOGIN_SERVER}/${IMAGE_NAME}:${TAG}"

log "コンテナーイメージをビルドします: ${IMAGE}"
az acr build \
  --registry "${REGISTRY}" \
  --image "${IMAGE_NAME}:${TAG}" \
  --image "${IMAGE_NAME}:latest" \
  --file "${REPO_ROOT}/portal/Dockerfile" \
  --output none \
  "${REPO_ROOT}"

save_state_value PORTAL_IMAGE "${IMAGE}"
export PORTAL_IMAGE="${IMAGE}"

log "Container App を更新します"
run_infra_deployment create
capture_outputs

PORTAL_URL="$(output_value portalUrl)"
CONTAINER_APP="$(output_value portalContainerAppName)"

log "リビジョンの状態を確認します"
az containerapp revision list \
  --name "${CONTAINER_APP}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query "[?properties.active].{name:name, active:properties.active, running:properties.runningState, replicas:properties.replicas}" \
  -o table

log "Azure News Portal: ${PORTAL_URL}"
log "ヘルスチェック: curl -fsS ${PORTAL_URL}/healthz"

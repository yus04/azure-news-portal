#!/usr/bin/env bash
# エンドツーエンドの動作確認を行います。

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

init

STORAGE="$(output_value storageAccountName)"
INPUT_CONTAINER="$(output_value inputContainerName)"
IMAGES_CONTAINER="$(output_value imagesContainerName)"
COSMOS_ACCOUNT="$(output_value cosmosAccountName)"
DATABASE="$(output_value cosmosDatabaseName)"
ARTICLES="$(output_value cosmosArticlesContainerName)"
FUNCTION_APP="$(output_value functionAppName)"
PORTAL_URL="$(output_value portalUrl)"

status=0
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  \033[1;32mOK\033[0m   %s\n' "${label}"
  else
    printf '  \033[1;31mNG\033[0m   %s\n' "${label}"
    status=1
  fi
}

log "リソースの状態"
check "Function App が Running" \
  bash -c "[[ \$(az functionapp show -g ${AZURE_RESOURCE_GROUP} -n ${FUNCTION_APP} --query state -o tsv) == 'Running' ]]"
check "ProcessArticleBlob が登録済み" \
  az functionapp function show -g "${AZURE_RESOURCE_GROUP}" -n "${FUNCTION_APP}" --function-name ProcessArticleBlob
check "Event Grid Subscription が有効" \
  az eventgrid system-topic event-subscription show \
    -g "${AZURE_RESOURCE_GROUP}" \
    --system-topic-name "$(output_value eventGridSystemTopicName)" \
    --name "$(output_value eventGridSubscriptionName)"

log "データ"
input_count="$(az storage blob list --account-name "${STORAGE}" --container-name "${INPUT_CONTAINER}" --auth-mode login --query 'length(@)' -o tsv 2>/dev/null || echo 0)"
image_count="$(az storage blob list --account-name "${STORAGE}" --container-name "${IMAGES_CONTAINER}" --auth-mode login --query 'length(@)' -o tsv 2>/dev/null || echo 0)"
printf '  入力記事 Blob      : %s 件\n' "${input_count}"
printf '  処理済み画像 Blob  : %s 件\n' "${image_count}"

article_count="$(az cosmosdb sql container query \
  --account-name "${COSMOS_ACCOUNT}" -g "${AZURE_RESOURCE_GROUP}" \
  --database-name "${DATABASE}" --name "${ARTICLES}" \
  --query-text "SELECT VALUE COUNT(1) FROM c WHERE c.processingStatus = 'succeeded'" \
  -o tsv 2>/dev/null || echo "?")"
failed_count="$(az cosmosdb sql container query \
  --account-name "${COSMOS_ACCOUNT}" -g "${AZURE_RESOURCE_GROUP}" \
  --database-name "${DATABASE}" --name "${ARTICLES}" \
  --query-text "SELECT VALUE COUNT(1) FROM c WHERE c.processingStatus = 'failed'" \
  -o tsv 2>/dev/null || echo "?")"
printf '  Cosmos DB 成功     : %s 件\n' "${article_count}"
printf '  Cosmos DB 失敗     : %s 件\n' "${failed_count}"

if [[ -n "${PORTAL_URL}" ]]; then
  log "Azure News Portal: ${PORTAL_URL}"
  check "ヘルスチェック /healthz" curl -fsS --max-time 60 "${PORTAL_URL}/healthz"
  check "readiness /readyz"      curl -fsS --max-time 60 "${PORTAL_URL}/readyz"
  check "記事 API /api/articles" curl -fsS --max-time 60 "${PORTAL_URL}/api/articles?size=1"
  check "ホーム画面 /"           curl -fsS --max-time 60 "${PORTAL_URL}/"
fi

exit "${status}"

#!/usr/bin/env bash
# 入力コンテナーの Blob を再アップロードして再処理をトリガーします。
#
#   ./scripts/reprocess.sh --prefix articles/2026/08     # 指定プレフィックス
#   ./scripts/reprocess.sh --failed                      # 失敗した記事のみ
#   ./scripts/reprocess.sh --blob articles/2026/08/28/x.json
#   ./scripts/reprocess.sh --all --dry-run
#
# 管理操作はパブリック API ではなくこの CLI から実行します。

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

PREFIX=""
SINGLE_BLOB=""
ONLY_FAILED=false
PROCESS_ALL=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)  PREFIX="$2"; shift 2 ;;
    --blob)    SINGLE_BLOB="$2"; shift 2 ;;
    --failed)  ONLY_FAILED=true; shift ;;
    --all)     PROCESS_ALL=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *)         fail "不明な引数: $1" ;;
  esac
done

if [[ -z "${PREFIX}" && -z "${SINGLE_BLOB}" && "${ONLY_FAILED}" == "false" && "${PROCESS_ALL}" == "false" ]]; then
  fail "--prefix / --blob / --failed / --all のいずれかを指定してください。"
fi

init

ACCOUNT="$(output_value storageAccountName)"
CONTAINER="$(output_value inputContainerName)"
COSMOS_ACCOUNT="$(output_value cosmosAccountName)"
DATABASE="$(output_value cosmosDatabaseName)"
ARTICLES="$(output_value cosmosArticlesContainerName)"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

collect_blobs() {
  if [[ -n "${SINGLE_BLOB}" ]]; then
    echo "${SINGLE_BLOB}"
    return
  fi

  if [[ "${ONLY_FAILED}" == "true" ]]; then
    log "失敗した記事を Cosmos DB から取得します" >&2
    az cosmosdb sql container query \
      --account-name "${COSMOS_ACCOUNT}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --database-name "${DATABASE}" \
      --name "${ARTICLES}" \
      --query-text "SELECT VALUE c.rawBlobPath FROM c WHERE c.processingStatus = 'failed'" \
      -o tsv 2>/dev/null | sed "s|^${CONTAINER}/||" || {
        warn "Cosmos DB のクエリに失敗しました。失敗記事 Blob コンテナーから推測します。"
        az storage blob list --account-name "${ACCOUNT}" --container-name "failed-articles" \
          --auth-mode login --query "[?!ends_with(name, '.error.json')].name" -o tsv
      }
    return
  fi

  az storage blob list \
    --account-name "${ACCOUNT}" \
    --container-name "${CONTAINER}" \
    --prefix "${PREFIX}" \
    --auth-mode login \
    --query "[?ends_with(name, '.json')].name" \
    -o tsv
}

count=0
while IFS= read -r blob; do
  [[ -n "${blob}" ]] || continue
  count=$((count + 1))
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '  (dry-run) %s\n' "${blob}"
    continue
  fi

  local_file="${TEMP_DIR}/$(echo "${blob}" | tr '/' '_')"
  log "再処理: ${blob}"
  az storage blob download \
    --account-name "${ACCOUNT}" --container-name "${CONTAINER}" \
    --name "${blob}" --file "${local_file}" --auth-mode login --output none
  az storage blob upload \
    --account-name "${ACCOUNT}" --container-name "${CONTAINER}" \
    --name "${blob}" --file "${local_file}" --content-type "application/json" \
    --overwrite true --auth-mode login --output none
done < <(collect_blobs)

log "対象 ${count} 件を処理しました (dry-run=${DRY_RUN})"
if [[ "${DRY_RUN}" == "false" && "${count}" -gt 0 ]]; then
  log "注意: 内容が変わっていない記事は contentHash により再処理がスキップされます。"
  log "      強制的に再処理する場合は infra の processingVersion を変更してください。"
fi

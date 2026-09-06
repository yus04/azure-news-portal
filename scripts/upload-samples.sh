#!/usr/bin/env bash
# サンプル記事 JSON を入力コンテナーへアップロードします (Event Grid が発火します)。
#
#   ./scripts/upload-samples.sh                 # samples/articles 配下をすべて
#   ./scripts/upload-samples.sh path/to/one.json

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

init

ACCOUNT="$(output_value storageAccountName)"
CONTAINER="$(output_value inputContainerName)"
PREFIX="${INPUT_BLOB_PREFIX:-articles}"

upload_one() {
  local file="$1"
  local relative="${file#"${REPO_ROOT}/samples/articles/"}"
  local blob="${PREFIX}/${relative}"
  log "アップロード: ${blob}"
  az storage blob upload \
    --account-name "${ACCOUNT}" \
    --container-name "${CONTAINER}" \
    --name "${blob}" \
    --file "${file}" \
    --content-type "application/json" \
    --overwrite true \
    --auth-mode login \
    --output none
}

if [[ $# -gt 0 ]]; then
  for file in "$@"; do
    [[ -f "${file}" ]] || fail "ファイルが見つかりません: ${file}"
    upload_one "$(cd "$(dirname "${file}")" && pwd)/$(basename "${file}")"
  done
else
  while IFS= read -r -d '' file; do
    upload_one "${file}"
  done < <(find "${REPO_ROOT}/samples/articles" -type f -name '*.json' -print0)
fi

log "アップロードが完了しました。処理状況は Application Insights で確認できます:"
cat <<'KQL'

  traces
  | where message has "article.succeeded" or message has "article.processing"
  | order by timestamp desc
  | take 50

KQL
log "Cosmos DB の件数確認: ./scripts/verify-deployment.sh"

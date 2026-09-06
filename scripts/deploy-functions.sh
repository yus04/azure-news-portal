#!/usr/bin/env bash
# Function コードをパッケージ化して Flex Consumption の Function App へデプロイします。

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

init
require_command zip

FUNCTION_APP="${1:-$(output_value functionAppName)}"
BUILD_DIR="${REPO_ROOT}/.dist/functions"
PACKAGE="${REPO_ROOT}/.dist/functions.zip"

log "デプロイパッケージを作成します: ${PACKAGE}"
rm -rf "${BUILD_DIR}" "${PACKAGE}"
mkdir -p "${BUILD_DIR}"

cp "${REPO_ROOT}/functions/function_app.py" "${BUILD_DIR}/"
cp "${REPO_ROOT}/functions/host.json" "${BUILD_DIR}/"
cp "${REPO_ROOT}/functions/requirements.txt" "${BUILD_DIR}/"
cp -r "${REPO_ROOT}/functions/src" "${BUILD_DIR}/src"

# 共有スキーマパッケージをパッケージルートへ配置する (Portal と同一定義)。
cp -r "${REPO_ROOT}/shared/newsportal_shared" "${BUILD_DIR}/newsportal_shared"

find "${BUILD_DIR}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${BUILD_DIR}" -name '*.pyc' -delete 2>/dev/null || true

(cd "${BUILD_DIR}" && zip -qr "${PACKAGE}" .)
log "パッケージサイズ: $(du -h "${PACKAGE}" | cut -f1)"

log "Function App へデプロイします: ${FUNCTION_APP}"
if ! az functionapp deploy \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${FUNCTION_APP}" \
      --src-path "${PACKAGE}" \
      --type zip \
      --output none; then
  warn "'az functionapp deploy' が失敗しました。config-zip でリトライします。"
  az functionapp deployment source config-zip \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${FUNCTION_APP}" \
    --src "${PACKAGE}" \
    --output none
fi

log "関数の登録を確認します (リモートビルドの完了まで数分かかる場合があります)"
for attempt in $(seq 1 30); do
  if az functionapp function show \
       --resource-group "${AZURE_RESOURCE_GROUP}" \
       --name "${FUNCTION_APP}" \
       --function-name ProcessArticleBlob >/dev/null 2>&1; then
    log "ProcessArticleBlob を検出しました"
    exit 0
  fi
  printf '.'
  sleep 20
done

printf '\n'
warn "ProcessArticleBlob をまだ検出できません。Application Insights のログを確認してください。"
warn "検出後に ./scripts/configure-event-grid.sh を実行してください。"
exit 1

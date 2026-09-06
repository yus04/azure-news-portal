#!/usr/bin/env bash
# すべてのリソースを削除します。
#
#   ./scripts/destroy.sh              # 確認あり
#   ./scripts/destroy.sh --yes        # 確認なし
#   ./scripts/destroy.sh --yes --no-wait

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ASSUME_YES=false
NO_WAIT=false
for arg in "$@"; do
  case "${arg}" in
    --yes|-y)  ASSUME_YES=true ;;
    --no-wait) NO_WAIT=true ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *)         fail "不明な引数: ${arg}" ;;
  esac
done

init

if ! az group show --name "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  log "リソースグループが存在しません: ${AZURE_RESOURCE_GROUP}"
  exit 0
fi

FOUNDRY_NAME=""
FOUNDRY_LOCATION=""
if [[ -f "${OUTPUTS_JSON}" ]]; then
  FOUNDRY_NAME="$(output_value foundryAccountName 2>/dev/null || true)"
  FOUNDRY_LOCATION="${AZURE_FOUNDRY_LOCATION}"
fi

if [[ "${ASSUME_YES}" == "false" ]]; then
  warn "リソースグループ '${AZURE_RESOURCE_GROUP}' 内のすべてのリソースを削除します。"
  read -r -p "続行するには リソースグループ名 を入力してください: " confirm
  [[ "${confirm}" == "${AZURE_RESOURCE_GROUP}" ]] || fail "入力が一致しませんでした。中止します。"
fi

log "リソースグループを削除します: ${AZURE_RESOURCE_GROUP}"
if [[ "${NO_WAIT}" == "true" ]]; then
  az group delete --name "${AZURE_RESOURCE_GROUP}" --yes --no-wait
  warn "--no-wait のため削除完了を待機しません。Foundry の purge は手動で実行してください。"
else
  az group delete --name "${AZURE_RESOURCE_GROUP}" --yes

  # Microsoft Foundry (Cognitive Services) は論理削除されるため purge が必要。
  if [[ -n "${FOUNDRY_NAME}" && -n "${FOUNDRY_LOCATION}" ]]; then
    log "論理削除された Foundry アカウントを完全削除します: ${FOUNDRY_NAME}"
    az cognitiveservices account purge \
      --name "${FOUNDRY_NAME}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --location "${FOUNDRY_LOCATION}" \
      --output none 2>/dev/null || warn "purge に失敗しました (既に削除済みの可能性があります)"
  fi
fi

rm -f "${OUTPUTS_JSON}" "${STATE_FILE}"
rm -rf "${REPO_ROOT}/.dist"
log "削除が完了しました。"

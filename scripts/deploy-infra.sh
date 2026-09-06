#!/usr/bin/env bash
# インフラ全体を検証してデプロイします。
#
#   ./scripts/deploy-infra.sh              # lint + validate + what-if + deploy
#   ./scripts/deploy-infra.sh --validate-only
#   ./scripts/deploy-infra.sh --skip-what-if

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

VALIDATE_ONLY=false
SKIP_WHAT_IF=false
for arg in "$@"; do
  case "${arg}" in
    --validate-only) VALIDATE_ONLY=true ;;
    --skip-what-if)  SKIP_WHAT_IF=true ;;
    -h|--help)       sed -n '2,7p' "$0"; exit 0 ;;
    *)               fail "不明な引数: ${arg}" ;;
  esac
done

init

log "Bicep を lint / build します"
az bicep build --file "${REPO_ROOT}/infra/main.bicep" --stdout > /dev/null
az bicep build-params --file "${REPO_ROOT}/infra/main.bicepparam" --stdout > /dev/null

ensure_resource_group

log "デプロイを検証します (validate)"
run_infra_deployment validate

if [[ "${SKIP_WHAT_IF}" == "false" ]]; then
  log "変更内容を確認します (what-if)"
  az deployment group what-if \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "$(deployment_name)" \
    --template-file "${REPO_ROOT}/infra/main.bicep" \
    --parameters "${REPO_ROOT}/infra/main.bicepparam" \
    --no-pretty-print > /dev/null || warn "what-if の実行に失敗しました (デプロイは継続します)"
fi

if [[ "${VALIDATE_ONLY}" == "true" ]]; then
  log "--validate-only が指定されたため、ここで終了します"
  exit 0
fi

log "インフラをデプロイします (数分かかります)"
run_infra_deployment create
capture_outputs

log "完了しました。主な出力:"
printf '  Function App          : %s\n' "$(output_value functionAppName)"
printf '  Storage Account       : %s\n' "$(output_value storageAccountName)"
printf '  Cosmos DB             : %s\n' "$(output_value cosmosAccountName)"
printf '  Foundry               : %s\n' "$(output_value foundryAccountName)"
printf '  Container Registry    : %s\n' "$(output_value containerRegistryName)"
printf '  Container App         : %s\n' "$(output_value portalContainerAppName)"
log "次の手順: ./scripts/deploy-functions.sh"

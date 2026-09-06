#!/usr/bin/env bash
# 各デプロイスクリプトが読み込む共通関数。
# すべてのスクリプトは再実行可能 (冪等) です。

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

STATE_FILE="${REPO_ROOT}/.deploy-outputs.env"
OUTPUTS_JSON="${REPO_ROOT}/azure-outputs.json"

# --- 表示 -------------------------------------------------------------------

log()   { printf '\033[1;34m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
fail()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 前提条件 ---------------------------------------------------------------

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 が見つかりません。README の前提条件を確認してください。"
}

require_azure_cli() {
  require_command az
  local version
  version="$(az version --query '"azure-cli"' -o tsv)"
  log "Azure CLI ${version}"
  az bicep version >/dev/null 2>&1 || az bicep install
}

require_login() {
  az account show >/dev/null 2>&1 || fail "Azure にログインしていません。'az login' を実行してください。"
  if [[ -n "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
    az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
  fi
  local sub
  sub="$(az account show --query '[name, id]' -o tsv | paste -sd' / ' -)"
  log "サブスクリプション: ${sub}"
}

# --- 設定 -------------------------------------------------------------------

load_env() {
  if [[ -f "${REPO_ROOT}/.env" ]]; then
    # shellcheck disable=SC1091
    set -a; source "${REPO_ROOT}/.env"; set +a
  fi

  AZURE_ENV_NAME="${AZURE_ENV_NAME:-dev}"
  AZURE_NAME_PREFIX="${AZURE_NAME_PREFIX:-newsportal}"
  AZURE_LOCATION="${AZURE_LOCATION:-japaneast}"
  AZURE_FOUNDRY_LOCATION="${AZURE_FOUNDRY_LOCATION:-eastus2}"
  AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-${AZURE_NAME_PREFIX}-${AZURE_ENV_NAME}}"
  PORTAL_IMAGE_NAME="${PORTAL_IMAGE_NAME:-azure-news-portal}"

  export AZURE_ENV_NAME AZURE_NAME_PREFIX AZURE_LOCATION AZURE_FOUNDRY_LOCATION AZURE_RESOURCE_GROUP
}

load_state() {
  if [[ -f "${STATE_FILE}" ]]; then
    # shellcheck disable=SC1090
    set -a; source "${STATE_FILE}"; set +a
  fi
}

save_state_value() {
  local key="$1" value="$2"
  touch "${STATE_FILE}"
  local tmp
  tmp="$(mktemp)"
  grep -v "^${key}=" "${STATE_FILE}" > "${tmp}" || true
  printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
  mv "${tmp}" "${STATE_FILE}"
  export "${key}=${value}"
}

# --- Azure 操作 -------------------------------------------------------------

ensure_resource_group() {
  if ! az group show --name "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
    log "リソースグループを作成します: ${AZURE_RESOURCE_GROUP} (${AZURE_LOCATION})"
    az group create --name "${AZURE_RESOURCE_GROUP}" --location "${AZURE_LOCATION}" --output none
  else
    log "リソースグループは既に存在します: ${AZURE_RESOURCE_GROUP}"
  fi
}

deployment_name() {
  echo "newsportal-${AZURE_ENV_NAME}"
}

# インフラをデプロイします。環境変数 PORTAL_IMAGE / DEPLOY_EVENT_GRID_SUBSCRIPTION が
# bicepparam の readEnvironmentVariable() 経由で反映されます。
run_infra_deployment() {
  local mode="${1:-create}"
  export PORTAL_IMAGE="${PORTAL_IMAGE:-}"
  export DEPLOY_EVENT_GRID_SUBSCRIPTION="${DEPLOY_EVENT_GRID_SUBSCRIPTION:-false}"

  log "Bicep パラメーター: env=${AZURE_ENV_NAME} location=${AZURE_LOCATION} foundry=${AZURE_FOUNDRY_LOCATION}"
  log "  PORTAL_IMAGE=${PORTAL_IMAGE:-(placeholder)}"
  log "  DEPLOY_EVENT_GRID_SUBSCRIPTION=${DEPLOY_EVENT_GRID_SUBSCRIPTION}"

  az deployment group "${mode}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "$(deployment_name)" \
    --template-file "${REPO_ROOT}/infra/main.bicep" \
    --parameters "${REPO_ROOT}/infra/main.bicepparam" \
    --output none
}

capture_outputs() {
  log "デプロイ出力を保存します: ${OUTPUTS_JSON}"
  az deployment group show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "$(deployment_name)" \
    --query properties.outputs \
    -o json > "${OUTPUTS_JSON}"

  while IFS=$'\t' read -r key value; do
    local upper
    upper="$(echo "${key}" | sed -E 's/([a-z0-9])([A-Z])/\1_\2/g' | tr '[:lower:]' '[:upper:]')"
    save_state_value "OUT_${upper}" "${value}"
  done < <(python3 - "${OUTPUTS_JSON}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
for key, item in data.items():
    print(f"{key}\t{item.get('value', '')}")
PY
)
}

output_value() {
  local key="$1"
  [[ -f "${OUTPUTS_JSON}" ]] || fail "${OUTPUTS_JSON} がありません。先に scripts/deploy-infra.sh を実行してください。"
  python3 - "${OUTPUTS_JSON}" "${key}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
value = data.get(sys.argv[2], {}).get("value", "")
if not value:
    sys.exit(f"output '{sys.argv[2]}' が見つかりません")
print(value)
PY
}

init() {
  load_env
  load_state
  require_azure_cli
  require_login
}

#!/usr/bin/env bash
# 入力コンテナーの過去 Blob をまとめて再処理 (バックフィル) します。
#
#   ./scripts/backfill.sh --from 2026-01 --to 2026-09
#   ./scripts/backfill.sh --all --batch-size 20 --delay 30
#
# Event Grid と Foundry のスロットリングを避けるため、バッチ単位で待機します。

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

FROM=""
TO=""
ALL=false
BATCH_SIZE=20
DELAY=30
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)       FROM="$2"; shift 2 ;;
    --to)         TO="$2"; shift 2 ;;
    --all)        ALL=true; shift ;;
    --batch-size) BATCH_SIZE="$2"; shift 2 ;;
    --delay)      DELAY="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=true; shift ;;
    -h|--help)    sed -n '2,9p' "$0"; exit 0 ;;
    *)            fail "不明な引数: $1" ;;
  esac
done

[[ "${ALL}" == "true" || -n "${FROM}" ]] || fail "--all または --from を指定してください。"

init

ACCOUNT="$(output_value storageAccountName)"
CONTAINER="$(output_value inputContainerName)"
PREFIX="${INPUT_BLOB_PREFIX:-articles}"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

in_range() {
  local blob="$1"
  [[ "${ALL}" == "true" ]] && return 0
  # 想定パス: <prefix>/YYYY/MM/DD/<id>.json
  local path="${blob#"${PREFIX}/"}"
  local year="${path%%/*}"
  local rest="${path#*/}"
  local month="${rest%%/*}"
  local stamp="${year}-${month}"
  [[ -n "${FROM}" && "${stamp}" < "${FROM}" ]] && return 1
  [[ -n "${TO}" && "${stamp}" > "${TO}" ]] && return 1
  return 0
}

mapfile -t blobs < <(
  az storage blob list \
    --account-name "${ACCOUNT}" \
    --container-name "${CONTAINER}" \
    --prefix "${PREFIX}" \
    --auth-mode login \
    --query "[?ends_with(name, '.json')].name" \
    -o tsv
)

log "候補 Blob: ${#blobs[@]} 件"

processed=0
batch=0
for blob in "${blobs[@]}"; do
  in_range "${blob}" || continue

  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '  (dry-run) %s\n' "${blob}"
    processed=$((processed + 1))
    continue
  fi

  local_file="${TEMP_DIR}/$(echo "${blob}" | tr '/' '_')"
  az storage blob download \
    --account-name "${ACCOUNT}" --container-name "${CONTAINER}" \
    --name "${blob}" --file "${local_file}" --auth-mode login --output none
  az storage blob upload \
    --account-name "${ACCOUNT}" --container-name "${CONTAINER}" \
    --name "${blob}" --file "${local_file}" --content-type "application/json" \
    --overwrite true --auth-mode login --output none
  rm -f "${local_file}"

  processed=$((processed + 1))
  batch=$((batch + 1))
  if (( batch >= BATCH_SIZE )); then
    log "${processed} 件を投入しました。${DELAY} 秒待機します..."
    sleep "${DELAY}"
    batch=0
  fi
done

log "バックフィル完了: ${processed} 件 (dry-run=${DRY_RUN})"

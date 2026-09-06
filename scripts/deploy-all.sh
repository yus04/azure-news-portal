#!/usr/bin/env bash
# インフラ → Function → Event Grid → Portal をまとめてデプロイします。
# 何度でも再実行できます。

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

init

log "==== 1/5 インフラ ===="
"${SCRIPT_DIR}/deploy-infra.sh" "$@"

log "==== 2/5 Function コード ===="
"${SCRIPT_DIR}/deploy-functions.sh"

log "==== 3/5 Event Grid Subscription ===="
"${SCRIPT_DIR}/configure-event-grid.sh"

log "==== 4/5 Portal コンテナー ===="
"${SCRIPT_DIR}/deploy-portal.sh"

log "==== 5/5 動作確認 ===="
"${SCRIPT_DIR}/verify-deployment.sh" || warn "確認で失敗した項目があります"

log "デプロイが完了しました。サンプル記事の投入: ./scripts/upload-samples.sh"

# 運用手順

日常運用と障害対応の手順をまとめます。デプロイ手順は [README.md](../README.md) を参照してください。

---

## 1. 日次の健全性確認

```bash
./scripts/verify-deployment.sh
```

確認項目: Function App の状態、`ProcessArticleBlob` の登録、Event Grid Subscription、
入力 / 画像 Blob 件数、Cosmos DB の成功・失敗件数、Portal の各エンドポイント。

### 監視すべき指標

| 指標 | 取得方法 | 目安 |
|------|---------|------|
| 記事処理の失敗率 | KQL `article.processing.failed` / 全体 | 5% 未満 |
| Foundry 呼び出しの P95 | KQL `foundry.completed` の `durationMs` | 60 秒未満 |
| デッドレター件数 | `eventgrid-deadletter` コンテナーの Blob 数 | 0 |
| `processingStatus = 'failed'` の記事数 | Cosmos DB クエリ | 0 |
| Cosmos DB の 429 | `dependencies` の結果コード | 0 |
| Portal の 5xx 率 | `requests` テーブル | 1% 未満 |

---

## 2. アラート設定の例

```bash
RG=rg-newsportal-dev
APPI_ID=$(az monitor app-insights component show -g "$RG" -a <appi-name> --query id -o tsv)

# 記事処理の失敗が 1 時間に 5 件以上
az monitor scheduled-query create \
  --name "article-processing-failures" \
  --resource-group "$RG" \
  --scopes "$APPI_ID" \
  --condition "count 'failures' > 5" \
  --condition-query failures="traces | where message has 'article.processing.failed'" \
  --evaluation-frequency 15m \
  --window-size 1h \
  --severity 2
```

Foundry のスロットリング (429) と Cosmos DB の RU 上限も同様に監視対象へ追加してください。

---

## 3. 失敗記事の調査と再処理

### 3.1 失敗記事の一覧

```bash
OUT() { python3 -c "import json;print(json.load(open('azure-outputs.json'))['$1']['value'])"; }

az cosmosdb sql container query \
  --account-name "$(OUT cosmosAccountName)" --resource-group rg-newsportal-dev \
  --database-name "$(OUT cosmosDatabaseName)" --name "$(OUT cosmosArticlesContainerName)" \
  --query-text "SELECT c.id, c.title, c.lastError, c.retryCount, c.rawBlobPath FROM c WHERE c.processingStatus = 'failed'" \
  -o table
```

### 3.2 正規化に失敗した入力の確認

```bash
ST=$(OUT storageAccountName)
az storage blob list --account-name "$ST" --container-name failed-articles \
  --auth-mode login --query "[?ends_with(name,'.error.json')].name" -o tsv

az storage blob download --account-name "$ST" --container-name failed-articles \
  --name "<blob>.error.json" --file /tmp/error.json --auth-mode login
cat /tmp/error.json
```

`reason` フィールドに欠落した必須項目や解析エラーが記録されています。

### 3.3 再処理

```bash
./scripts/reprocess.sh --failed
./scripts/reprocess.sh --prefix articles/2026/09
./scripts/reprocess.sh --blob articles/2026/09/02/foundry-agent-observability-preview.json
```

内容が変わっていない記事はスキップされます。強制再処理は `PROCESSING_VERSION` を変更します。

---

## 4. デッドレターの処理

Event Grid が再試行上限 (10 回) または TTL (24 時間) を超えたイベントは
`eventgrid-deadletter` コンテナーへ書き込まれます。

```bash
ST=$(OUT storageAccountName)
az storage blob list --account-name "$ST" --container-name eventgrid-deadletter \
  --auth-mode login -o table

# 内容を確認 (Event Grid イベントの JSON 配列)
az storage blob download --account-name "$ST" --container-name eventgrid-deadletter \
  --name "<blob>" --file /tmp/dlq.json --auth-mode login
python3 -m json.tool /tmp/dlq.json | head -50
```

対象 Blob のパスを特定したら `./scripts/reprocess.sh --blob <path>` で再投入します。
処理が成功したらデッドレター Blob を削除します。

```bash
az storage blob delete --account-name "$ST" --container-name eventgrid-deadletter \
  --name "<blob>" --auth-mode login
```

---

## 5. モデルの入れ替え

1. 新モデルのリージョン提供状況とクォータを確認 (README 10 章)
2. `.env` で `FOUNDRY_MODEL_NAME` / `FOUNDRY_DEPLOYMENT_NAME` などを変更
3. `./scripts/deploy-infra.sh --skip-what-if` でモデルデプロイを追加
4. `PROCESSING_VERSION` を上げる (再処理時に新モデルの結果で上書きされます)
5. 少数記事で品質を確認

```bash
./scripts/reprocess.sh --prefix articles/2026/09/02
```

6. 問題なければ `./scripts/backfill.sh --all --batch-size 20 --delay 30` で全件再処理
7. 旧モデルのデプロイを削除

```bash
az cognitiveservices account deployment delete \
  -g rg-newsportal-dev -n <foundry-account> --deployment-name <old-deployment>
```

---

## 6. Portal の更新とロールバック

```bash
# 新しいイメージをビルドしてデプロイ
PORTAL_IMAGE_TAG=v1.1.0 ./scripts/deploy-portal.sh

# リビジョン一覧
az containerapp revision list -g rg-newsportal-dev -n <container-app> -o table

# 直前のリビジョンへ戻す (single revision mode のためイメージを戻して再デプロイ)
PORTAL_IMAGE_TAG=v1.0.0 ./scripts/deploy-portal.sh
```

---

## 7. コスト確認

```bash
az consumption usage list --start-date 2026-09-01 --end-date 2026-09-30 \
  --query "[?contains(instanceName, 'newsportal')].{name:instanceName, meter:meterDetails.meterName, cost:pretaxCost}" \
  -o table
```

Foundry のトークン消費は Application Insights の KQL でも確認できます。

```kusto
traces
| where message has "foundry.completed"
| extend p = parse_json(message)
| summarize promptTokens = sum(toint(p.promptTokens)),
            completionTokens = sum(toint(p.completionTokens)),
            calls = count()
    by bin(timestamp, 1d)
| order by timestamp desc
```

---

## 8. データのクリーンアップ

`processing-state` コンテナーは TTL 30 日で自動削除されます。
古い記事や画像を削除する場合:

```bash
# 2025 年以前の記事を削除 (パーティションキー単位で実行)
az cosmosdb sql container query \
  --account-name "$(OUT cosmosAccountName)" --resource-group rg-newsportal-dev \
  --database-name "$(OUT cosmosDatabaseName)" --name "$(OUT cosmosArticlesContainerName)" \
  --query-text "SELECT c.id, c.partitionKey FROM c WHERE c.partitionKey < '2025-01'" -o tsv

# 対応する画像 Blob
az storage blob delete-batch --account-name "$(OUT storageAccountName)" \
  --source article-images --pattern "<articleId>/*" --auth-mode login
```

削除は不可逆です。実行前に必ず対象を確認してください。

---

## 9. セキュリティレビューのチェックリスト

- [ ] Storage の `allowSharedKeyAccess` が `false`
- [ ] Cosmos DB の `disableLocalAuth` が `true`
- [ ] Foundry の `disableLocalAuth` が `true`
- [ ] ACR の `adminUserEnabled` が `false`
- [ ] アプリ設定に接続文字列やキーが含まれていない
- [ ] ロール割り当てが Function / Portal の 2 つの ID に限定されている
- [ ] Portal の応答に CSP とセキュアヘッダーが含まれる
- [ ] 依存パッケージのバージョンが固定されている
- [ ] Application Insights に本文や秘密情報が記録されていない

```bash
# 設定の一括確認
ST=$(OUT storageAccountName)
az storage account show -g rg-newsportal-dev -n "$ST" \
  --query "{sharedKey:allowSharedKeyAccess, tls:minimumTlsVersion, https:supportsHttpsTrafficOnly}"
az cosmosdb show -g rg-newsportal-dev -n "$(OUT cosmosAccountName)" --query "{localAuth:disableLocalAuth}"
az cognitiveservices account show -g rg-newsportal-dev -n "$(OUT foundryAccountName)" \
  --query "{localAuth:properties.disableLocalAuth}"
az acr show -g rg-newsportal-dev -n "$(OUT containerRegistryName)" --query "{admin:adminUserEnabled}"
curl -sI "$(OUT portalUrl)/" | grep -i "content-security-policy\|x-frame-options\|x-content-type"
```

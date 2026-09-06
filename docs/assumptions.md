# 前提と未確定事項

実装時に確定できなかった事項と、採用した既定値・その理由を記録します。
不明点を黙って推測せず、ここに明示したうえで実装を進めています。

---

## 1. リポジトリの初期状態

**確認結果**: 実装開始時点で `/home/yu/azure-news-portal` は空のディレクトリでした。
既存コード、既存ワークフロー、既存の Bicep は存在しません。

**影響**: 「既存コードやワークフローを壊さない」制約は自動的に満たされます。
Azure Feed リポジトリの fork と Blob Storage への保存処理は本リポジトリの対象外です。

---

## 2. 入力 Blob の形式

**未確定**: 実際に `raw-articles` へ保存される JSON のスキーマは確認できませんでした
(Blob Storage へのアップロードは別途完了済みという前提のみ)。

**採用した既定値**: 複数の項目名を許容するアダプター (`functions/src/newsproc/adapters.py`) を実装しました。

| 内部項目 | 許容する入力項目名 |
|---------|------------------|
| タイトル | `title`, `headline`, `name`, `subject` |
| 元記事 URL | `url`, `originalUrl`, `link`, `canonicalUrl`, `permalink`, `articleUrl`, `webUrl` |
| 情報源 | `source`, `sourceName`, `feed`, `feedName`, `siteName`, `publisher`, `provider` |
| 公開日時 | `publishedAt`, `published`, `pubDate`, `datePublished`, `publishDate`, `date`, `isoDate` |
| 取り込み日時 | `ingestedAt`, `fetchedAt`, `collectedAt`, `crawledAt`, `retrievedAt` |
| 概要 | `summary`, `description`, `excerpt`, `abstract`, `snippet`, `contentSnippet` |
| 本文 | `content`, `body`, `contentHtml`, `content:encoded`, `articleBody`, `fullText`, `text` |
| カテゴリ | `category`, `sourceCategory`, `section`, `categories`, `topic`, `topics` |
| 著者 | `author`, `authors`, `creator`, `byline`, `dc:creator` |
| 画像 | `images`, `image`, `imageUrl`, `thumbnail`, `ogImage`, `enclosure`, `media` |

また `article` / `item` / `entry` / `data` / `payload` / `record` による入れ子も自動的に展開します。

**必須項目**: タイトル、元記事 URL、公開日時。いずれかが欠落または解析不能な場合は
推測で補完せず、構造化ログへ記録し `failed-articles` コンテナーへ退避して処理を失敗させます。

**例外的に補完する項目**: `source` が欠落している場合のみ、正規化した元記事 URL のホスト名
(`www.` を除去) を使用します。これは推測ではなく URL からの決定的な導出であり、
情報源が空だと Portal のフィルターが機能しないためです。

**Blob パス**: 推奨形式は `raw/articles/年/月/日/記事ID.json` ですが、実装は
入力コンテナー内の任意の `.json` パスを受け付けます。付属スクリプトは
`articles/YYYY/MM/DD/<id>.json` へアップロードします (`INPUT_BLOB_PREFIX` で変更可)。

---

## 3. モデル `gpt-5.6-luna`

**未確定**: `gpt-5.6-luna` の提供リージョン、モデルバージョン文字列、対応 API
(Chat Completions / Responses)、対応パラメーター (`reasoning_effort`,
`max_completion_tokens`, `json_schema` 構造化出力) を公式ドキュメントで確認できませんでした。

**採用した方針**: モデルを Bicep パラメーターとコードから完全に切り離しました。
Bicep 全体を無断で別モデルに書き換えることはしていません。

| パラメーター | 既定値 | 変更方法 |
|-------------|-------|---------|
| `foundryModelName` | `gpt-5.6-luna` | `FOUNDRY_MODEL_NAME` 環境変数 |
| `foundryModelVersion` | 空 (バージョン指定なし) | `FOUNDRY_MODEL_VERSION` |
| `foundryDeploymentName` | `gpt-5-6-luna` | `FOUNDRY_DEPLOYMENT_NAME` |
| `foundryDeploymentSkuName` | `GlobalStandard` (Standard Global) | `FOUNDRY_DEPLOYMENT_SKU` |
| `foundryApiVersion` | `2025-04-01-preview` | `FOUNDRY_API_VERSION` |
| `foundryApiStyle` | `chat` | `FOUNDRY_API_STYLE` (`chat` / `responses`) |
| `foundryReasoningEffort` | `low` | `FOUNDRY_REASONING_EFFORT` (空で無効化) |

デプロイ名にドット (`.`) を使わず `gpt-5-6-luna` としたのは、Azure のデプロイ名として
安全な文字集合に収めるためです。モデル名 (`gpt-5.6-luna`) とは独立しています。

`foundryModelVersion` の既定を空にしたのは、存在しないバージョンを指定するとデプロイが
必ず失敗するためです。空の場合、Bicep は `model.version` プロパティ自体を送信せず、
サービス側の既定バージョンが使用されます。

**コード側の耐性**: モデルが特定パラメーターに対応していない場合、エラーメッセージから
該当パラメーターを検出して自動的に無効化し再試行します
(`reasoning_effort` → `temperature` → `max_completion_tokens` → `json_schema`)。
`json_schema` が使えない場合は `json_object` へフォールバックし、
いずれの場合も Pydantic で出力を検証します。

**リージョン**: 既定の Foundry リージョンは `eastus2` としています
(Azure OpenAI 系の新モデルが最も早く提供される傾向があるため)。
利用可否の確認手順は README の「モデルのリージョンとクォータ確認」を参照してください。

---

## 4. Functions の共有キー無効化

**確認事項**: Flex Consumption の Azure Functions は、`AzureWebJobsStorage__accountName` +
`AzureWebJobsStorage__credential=managedidentity` によるアイデンティティベース接続に対応しており、
デプロイコンテナーも `UserAssignedIdentity` 認証を指定できます。
このため `allowSharedKeyAccess: false` を採用しました。

**必要なロール** (Functions ホストの動作要件):
Storage Blob Data Contributor (アカウントスコープ)、Storage Queue Data Contributor、
Storage Table Data Contributor、およびデプロイコンテナーへの Storage Blob Data Owner。

**トレードオフ**: Functions ホストは `azure-webjobs-hosts` / `azure-webjobs-secrets` コンテナーを
実行時に自動作成するため、Blob 権限をアカウントスコープで付与する必要があります。
その結果、要件 7.1 の「入力記事 Blob の読み取り」「処理済み画像 Blob の読み書き」を
コンテナー単位に厳密分離することはできていません。

**完全分離する場合の選択肢** (今回は採用せず):
Functions ホスト専用のストレージアカウントを分離し、データ用アカウントには
コンテナースコープのロールのみを付与する。リソース数とコストが増えるため、
要件 5.2 の「1 つのストレージアカウント + 複数コンテナー」構成を優先しました。

**SCM の基本認証**: `az functionapp deploy` によるデプロイを成立させるため、
SCM の基本認証発行プロファイルは既定のまま有効にしています
(FTP は明示的に無効化)。CI/CD で Entra ID 認証のみに切り替える場合は
`scm` の `basicPublishingCredentialsPolicies` を `allow: false` にし、
`func azure functionapp publish` などの Entra ID 対応デプロイ手段へ切り替えてください。

---

## 5. Event Grid のデッドレター

Storage の共有キーを無効化しているため、Event Grid の既定のデッドレター書き込み
(キーベース) は使用できません。`deadLetterWithResourceIdentity` を使用し、
System Topic のシステム割り当て ID に `eventgrid-deadletter` コンテナーへの
Storage Blob Data Contributor を付与しています。

---

## 6. Container App の初回デプロイ

Container App は ACR にイメージが存在しない状態では起動できません。
`portalImage` パラメーターが空の場合は `mcr.microsoft.com/k8se/quickstart:latest`
(ポート 80) をプレースホルダーとして使用し、`registries` / 環境変数 / ヘルスプローブは設定しません。
`deploy-portal.sh` が ACR へイメージを push した後、同じテンプレートを
`portalImage` 付きで再適用して本番構成へ切り替えます。

---

## 7. Bicep のリソース型バージョン警告

ローカルの Bicep CLI (0.31.92) には `Microsoft.CognitiveServices/accounts@2025-06-01` と
`Microsoft.DocumentDB/databaseAccounts@2024-11-15` の型定義が含まれておらず、
`az bicep build` 時に `BCP081` 警告が出ます。これは型情報が無いことによる警告であり、
デプロイは可能です。Bicep CLI を最新版へ更新すると警告は解消します
(`az bicep upgrade`)。

---

## 8. Portal のユーザー認証

要件どおり、今回はユーザー認証を実装していません。
将来 Entra ID 認証を追加する場合は、Container Apps の組み込み認証を有効化し
(`Microsoft.App/containerApps/authConfigs`)、アプリ側で
`X-MS-CLIENT-PRINCIPAL` ヘッダーを解釈する依存関係を追加します。
アプリ側はミドルウェアの追加のみで対応できる構造にしています。

---

## 9. 画像の代替テキスト

モデルによる画像内容の説明は生成していません。
元サイトの `alt` / `title` 属性を優先し、いずれも無い場合は日本語タイトルを使用します。
画像とテキストを同時に扱うマルチモーダル呼び出しはトークンコストが大きく増えるため、
今回の要件 (要点と要約の生成) には含めない判断としました。

---

## 10. テストの実行環境

`pyproject.toml` の `[tool.pytest.ini_options].pythonpath` により、
`shared` / `functions` / `functions/src` / `portal` がテスト実行時のインポートパスへ追加されます。
Portal のテストは `PORTAL_OFFLINE_MODE=1` で `samples/cosmos/articles.json` を読み込む
インメモリリポジトリを使用し、Azure への接続は行いません。

実装検証時の環境では `python3 -m venv` が `ensurepip` の不足で使用できなかったため、
`pip install --target` による隔離ディレクトリで依存関係の解決とテスト実行を確認しています。
通常環境では README の手順どおり venv を使用してください。

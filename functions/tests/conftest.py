"""Functions テストの共通フィクスチャとテストダブル。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from newsportal_shared.article import ArticleDocument
from newsproc.config import CosmosSettings, FetchSettings, FoundrySettings, ImageSettings, Settings, StorageSettings
from newsproc.fetcher import FetchResult
from newsproc.foundry import InsightsResult
from newsproc.models import ArticleInsights


class FakeBlobStore:
    """メモリ上で Blob を模倣するテストダブル。"""

    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], bytes] = {}
        self.uploads: list[dict[str, Any]] = []
        self.download_error: Exception | None = None
        self.upload_error: Exception | None = None

    def put(self, container: str, blob_name: str, data: bytes | str | dict) -> None:
        if isinstance(data, dict):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        elif isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = data
        self.blobs[(container, blob_name)] = payload

    def download(self, container: str, blob_name: str, *, max_bytes: int | None = None) -> bytes:
        if self.download_error:
            raise self.download_error
        try:
            return self.blobs[(container, blob_name)]
        except KeyError as exc:
            raise FileNotFoundError(f"{container}/{blob_name}") from exc

    def upload(
        self,
        *,
        container: str,
        blob_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
        cache_control: str = "",
    ) -> str:
        if self.upload_error:
            raise self.upload_error
        self.blobs[(container, blob_name)] = data
        self.uploads.append({"container": container, "blob": blob_name, "contentType": content_type})
        return f"{container}/{blob_name}"


class FakeRepository:
    """Cosmos DB リポジトリのテストダブル。"""

    def __init__(self) -> None:
        self.articles: dict[str, dict[str, Any]] = {}
        self.states: list[dict[str, Any]] = []
        self.claimed_events: set[str] = set()
        self.upsert_error: Exception | None = None
        self.upsert_calls = 0

    def get_article(self, article_id: str, partition_key: str) -> dict[str, Any] | None:
        return self.articles.get(article_id)

    def upsert_article(self, document: ArticleDocument) -> dict[str, Any]:
        self.upsert_calls += 1
        if self.upsert_error:
            raise self.upsert_error
        payload = document.to_cosmos_dict()
        self.articles[document.id] = payload
        return payload

    def try_claim_event(self, event_id: str, article_id: str) -> bool:
        if not event_id:
            return True
        if event_id in self.claimed_events:
            return False
        self.claimed_events.add(event_id)
        return True

    def record_processing_state(self, article_id: str, status: str, **fields: Any) -> None:
        self.states.append({"articleId": article_id, "status": status, **fields})


class FakeGenerator:
    """Foundry モデルのテストダブル。"""

    def __init__(self, insights: ArticleInsights | None = None, error: Exception | None = None) -> None:
        self.insights = insights or default_insights()
        self.error = error
        self.calls = 0

    def generate(self, article, body_text):  # noqa: ANN001 - テストダブル
        self.calls += 1
        if self.error:
            raise self.error
        return InsightsResult(
            insights=self.insights,
            deployment="test-deployment",
            model_version="test-model-1",
            prompt_tokens=1200,
            completion_tokens=400,
            attempts=1,
            duration_ms=12.5,
        )


def default_insights() -> ArticleInsights:
    return ArticleInsights(
        title_ja="Azure Container Apps のサーバーレス GPU が一般提供開始",
        summary_ja="Azure Container Apps でサーバーレス GPU が GA。アイドル時はゼロにスケールする。",
        key_points_ja=["サーバーレス GPU が GA", "スケールゼロに対応", "秒単位課金"],
        target_audience=["アプリ開発者"],
        products=["Azure Container Apps"],
        terms=["スケールゼロ"],
        tags=["GA", "GPU"],
        category="新機能",
        update_type="ga",
        importance="high",
        importance_reason_ja="推論基盤の構成に影響するため。",
        search_keywords=["container apps", "gpu"],
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        storage=StorageSettings(
            account_name="stteststorage",
            blob_endpoint="https://stteststorage.blob.core.windows.net/",
            input_container="raw-articles",
            images_container="article-images",
            content_archive_container="article-content",
            failed_container="failed-articles",
        ),
        cosmos=CosmosSettings(endpoint="https://cosmos.example/", database_name="newsportal"),
        foundry=FoundrySettings(endpoint="https://foundry.example/", deployment="test-deployment"),
        fetch=FetchSettings(allow_article_fetch=False),
        images=ImageSettings(),
        processing_version="1.0.0",
        max_processing_retries=3,
    )


@pytest.fixture
def settings_with_fetch(settings: Settings) -> Settings:
    return replace(settings, fetch=replace(settings.fetch, allow_article_fetch=True, max_retries=0))


@pytest.fixture
def blob_store() -> FakeBlobStore:
    return FakeBlobStore()


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def generator() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def sample_input() -> dict[str, Any]:
    return {
        "id": "azure-container-apps-serverless-gpu-ga",
        "title": "Generally Available: Serverless GPUs in Azure Container Apps",
        "link": "https://azure.microsoft.com/en-us/updates/serverless-gpus-ga/?utm_source=rss",
        "source": "Azure Updates",
        "author": "Azure Container Apps Team",
        "pubDate": "2026-08-28T09:00:00Z",
        "ingestedAt": "2026-08-28T09:12:31Z",
        "category": "Compute",
        "summary": "Serverless GPUs are now generally available in Azure Container Apps.",
        "content": "<p>Serverless GPUs scale to zero when idle.</p>",
        "images": ["https://azure.microsoft.com/assets/hero-gpu.png"],
    }


def blob_created_event(
    *,
    event_id: str = "11111111-2222-3333-4444-555555555555",
    container: str = "raw-articles",
    blob_name: str = "2026/08/28/article.json",
    account: str = "stteststorage",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "eventType": "Microsoft.Storage.BlobCreated",
        "subject": f"/blobServices/default/containers/{container}/blobs/{blob_name}",
        "eventTime": "2026-08-28T09:12:31Z",
        "data": {
            "api": "PutBlob",
            "url": f"https://{account}.blob.core.windows.net/{container}/{blob_name}",
            "eTag": "0x8D000000000000",
            "contentLength": 1024,
            "contentType": "application/json",
        },
    }


def make_fetch_result(html: str, url: str = "https://azure.microsoft.com/article") -> FetchResult:
    return FetchResult(
        url=url,
        status_code=200,
        content_type="text/html; charset=utf-8",
        content=html.encode("utf-8"),
    )

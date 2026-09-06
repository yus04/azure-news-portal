"""Cosmos DB for NoSQL への書き込み (Managed Identity 認証)。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError
from newsportal_shared.article import ArticleDocument

from newsproc.config import CosmosSettings
from newsproc.logging_utils import log_info, log_warning


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ArticleRepository:
    """記事ドキュメントの読み書き。"""

    def __init__(self, settings: CosmosSettings, credential: Any, *, client: CosmosClient | None = None) -> None:
        self._settings = settings
        self._client = client or CosmosClient(url=settings.endpoint, credential=credential)
        database = self._client.get_database_client(settings.database_name)
        self._articles = database.get_container_client(settings.articles_container)
        self._state = database.get_container_client(settings.state_container)

    # -- 記事 ----------------------------------------------------------------

    def get_article(self, article_id: str, partition_key: str) -> dict[str, Any] | None:
        try:
            return self._articles.read_item(item=article_id, partition_key=partition_key)
        except CosmosResourceNotFoundError:
            return None

    def upsert_article(self, document: ArticleDocument) -> dict[str, Any]:
        payload = document.to_cosmos_dict()
        result = self._articles.upsert_item(payload)
        log_info(
            "cosmos.upsert.completed",
            articleId=document.id,
            partitionKey=document.partition_key,
            processingStatus=document.processing_status,
            requestCharge=self._articles.client_connection.last_response_headers.get("x-ms-request-charge"),
        )
        return result

    # -- 処理状態 ------------------------------------------------------------

    def try_claim_event(self, event_id: str, article_id: str) -> bool:
        """イベントを初めて処理する場合のみ True を返します (重複イベント対策)。"""
        if not event_id:
            return True
        try:
            self._state.create_item(
                {
                    "id": f"evt-{event_id}",
                    "articleId": article_id,
                    "eventId": event_id,
                    "status": "claimed",
                    "updatedAt": _utcnow(),
                }
            )
            return True
        except CosmosResourceExistsError:
            log_warning("event.duplicate", eventId=event_id, articleId=article_id)
            return False
        except CosmosHttpResponseError as exc:
            # 状態管理の失敗で記事処理そのものを止めない (upsert により冪等性は保たれる)。
            log_warning("event.claim.failed", eventId=event_id, statusCode=exc.status_code)
            return True

    def record_processing_state(self, article_id: str, status: str, **fields: Any) -> None:
        document = {
            "id": f"state-{article_id}",
            "articleId": article_id,
            "status": status,
            "updatedAt": _utcnow(),
        }
        document.update({k: v for k, v in fields.items() if v is not None})
        try:
            self._state.upsert_item(document)
        except CosmosHttpResponseError as exc:
            log_warning("state.upsert.failed", articleId=article_id, statusCode=exc.status_code)

    def get_retry_count(self, article_id: str) -> int:
        try:
            item = self._state.read_item(item=f"state-{article_id}", partition_key=article_id)
        except CosmosResourceNotFoundError:
            return 0
        except CosmosHttpResponseError:
            return 0
        value = item.get("retryCount", 0)
        return int(value) if isinstance(value, (int, float, str)) and str(value).isdigit() else 0

    def close(self) -> None:
        # CosmosClient はコンテキストマネージャーとしても利用可能。
        try:
            self._client.__exit__(None, None, None)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - クローズ失敗は無視する
            pass

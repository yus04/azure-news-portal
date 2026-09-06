"""記事処理パイプラインのオーケストレーション。

外部依存 (Blob / Cosmos / Foundry / HTTP) はすべてコンストラクター経由で注入するため、
テストではテストダブルへ差し替えられます。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

from newsportal_shared.article import (
    IMPORTANCE_RANK,
    ArticleDocument,
    ImageAsset,
    ProcessingStatus,
    build_partition_key,
    build_search_text,
)

from newsproc.adapters import normalize_input
from newsproc.config import Settings
from newsproc.fetcher import FetchError, fetch_url
from newsproc.foundry import FoundryError, InsightsGenerator
from newsproc.htmlx import ExtractedPage, ImageCandidate, extract_page
from newsproc.images import ImageProcessor
from newsproc.logging_utils import log_info, log_warning, timed
from newsproc.models import NormalizationError, NormalizedArticle
from newsproc.urls import content_hash

#: 入力 Blob の最大サイズ。
MAX_INPUT_BLOB_BYTES = 2 * 1024 * 1024

#: Cosmos DB へ保存せず Blob へ退避する本文の最大長。
MAX_ARCHIVED_TEXT_CHARS = 200_000

#: 一時的とみなすエラーカテゴリ (Event Grid の再試行対象)。
TRANSIENT_CATEGORIES = frozenset({"timeout", "network", "http_5xx", "http_429", "transient", "cosmos"})


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class BlobCreatedEvent:
    """Event Grid の BlobCreated イベントから抽出した情報。"""

    event_id: str
    blob_url: str
    container: str
    blob_name: str
    etag: str = ""
    content_length: int | None = None
    api: str = ""


@dataclass
class ProcessingOutcome:
    """1 件の処理結果。"""

    status: str
    article_id: str | None = None
    reason: str = ""
    retriable: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


class TransientProcessingError(Exception):
    """Event Grid に再試行させたい一時的エラー。"""


def parse_blob_created_event(event: dict[str, Any]) -> BlobCreatedEvent:
    """Event Grid イベント (EventGridSchema) を解析します。"""
    event_type = event.get("eventType") or event.get("event_type") or ""
    if event_type != "Microsoft.Storage.BlobCreated":
        raise ValueError(f"unsupported event type: {event_type}")

    data = event.get("data") or {}
    blob_url = data.get("url") or ""
    if not blob_url:
        raise ValueError("event data does not contain a blob url")

    path = unquote(urlsplit(blob_url).path).lstrip("/")
    container, _, blob_name = path.partition("/")
    if not container or not blob_name:
        raise ValueError(f"cannot determine container/blob from url path: {path}")

    return BlobCreatedEvent(
        event_id=str(event.get("id") or ""),
        blob_url=blob_url,
        container=container,
        blob_name=blob_name,
        etag=str(data.get("eTag") or ""),
        content_length=data.get("contentLength"),
        api=str(data.get("api") or ""),
    )


class ArticlePipeline:
    """BlobCreated イベント 1 件を処理します。"""

    def __init__(
        self,
        *,
        settings: Settings,
        blob_store: Any,
        repository: Any,
        generator: InsightsGenerator,
        fetch_fn=fetch_url,
    ) -> None:
        self._settings = settings
        self._blob_store = blob_store
        self._repository = repository
        self._generator = generator
        self._fetch_fn = fetch_fn

    # -- エントリーポイント --------------------------------------------------

    def handle_event(self, event: dict[str, Any]) -> ProcessingOutcome:
        try:
            parsed = parse_blob_created_event(event)
        except ValueError as exc:
            log_warning("event.invalid", reason=str(exc))
            return ProcessingOutcome(status="skipped", reason=str(exc))

        if parsed.container != self._settings.storage.input_container:
            log_info("event.ignored", reason="container_not_monitored", container=parsed.container)
            return ProcessingOutcome(status="skipped", reason="container_not_monitored")

        if not parsed.blob_name.lower().endswith(".json"):
            log_info("event.ignored", reason="not_json", blobPath=parsed.blob_name)
            return ProcessingOutcome(status="skipped", reason="not_json")

        return self.process_blob(parsed.container, parsed.blob_name, event_id=parsed.event_id)

    def process_blob(self, container: str, blob_name: str, *, event_id: str = "") -> ProcessingOutcome:
        metrics: dict[str, Any] = {}
        article: NormalizedArticle | None = None
        raw_bytes: bytes | None = None

        with timed("article.processing", eventId=event_id or None, blobPath=f"{container}/{blob_name}"):
            try:
                raw_bytes = self._blob_store.download(container, blob_name, max_bytes=MAX_INPUT_BLOB_BYTES)
                payload = json.loads(raw_bytes.decode("utf-8"))
                article = normalize_input(payload, raw_blob_path=f"{container}/{blob_name}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._archive_failure(blob_name, raw_bytes, f"invalid json: {exc}")
                log_warning("article.invalid_json", blobPath=f"{container}/{blob_name}")
                return ProcessingOutcome(status="failed", reason="invalid_json")
            except NormalizationError as exc:
                self._archive_failure(blob_name, raw_bytes, str(exc))
                log_warning(
                    "article.normalization_failed",
                    blobPath=f"{container}/{blob_name}",
                    missingFields=exc.missing_fields,
                )
                return ProcessingOutcome(status="failed", reason="normalization_failed")
            except Exception as exc:  # noqa: BLE001 - Blob 取得失敗は再試行対象
                log_warning("article.blob_download_failed", errorType=type(exc).__name__)
                raise TransientProcessingError(f"blob download failed: {type(exc).__name__}") from exc

            if not self._repository.try_claim_event(event_id, article.article_id):
                return ProcessingOutcome(status="skipped", article_id=article.article_id, reason="duplicate_event")

            partition_key = build_partition_key(article.published_at)
            input_hash = content_hash(
                article.normalized_url,
                article.title,
                article.published_at,
                article.summary_raw,
                article.body_raw,
            )

            existing = self._repository.get_article(article.article_id, partition_key)
            if self._can_skip(existing, input_hash):
                log_info("article.skipped", articleId=article.article_id, reason="unchanged")
                return ProcessingOutcome(status="skipped", article_id=article.article_id, reason="unchanged")

            retry_count = int((existing or {}).get("retryCount", 0) or 0)

            try:
                document = self._build_document(
                    article,
                    partition_key=partition_key,
                    input_hash=input_hash,
                    retry_count=retry_count,
                    metrics=metrics,
                )
            except (FetchError, FoundryError) as exc:
                category = getattr(exc, "category", "unknown")
                self._record_failure(article, partition_key, input_hash, retry_count, exc, existing)
                if category in TRANSIENT_CATEGORIES and retry_count < self._settings.max_processing_retries:
                    raise TransientProcessingError(f"{type(exc).__name__}: {category}") from exc
                return ProcessingOutcome(
                    status="failed",
                    article_id=article.article_id,
                    reason=f"{type(exc).__name__}:{category}",
                    metrics=metrics,
                )

            try:
                self._repository.upsert_article(document)
            except Exception as exc:  # noqa: BLE001 - 書き込み失敗は Event Grid に再試行させる
                log_warning("cosmos.upsert.failed", articleId=article.article_id, errorType=type(exc).__name__)
                raise TransientProcessingError(f"cosmos upsert failed: {type(exc).__name__}") from exc

            self._repository.record_processing_state(
                article.article_id,
                ProcessingStatus.succeeded.value,
                retryCount=retry_count,
                contentHash=input_hash,
            )
            metrics["imagesStored"] = len(document.image_assets)
            log_info(
                "article.succeeded",
                articleId=article.article_id,
                partitionKey=partition_key,
                source=article.source,
                importance=document.importance,
                **metrics,
            )
            return ProcessingOutcome(
                status="succeeded",
                article_id=article.article_id,
                metrics=metrics,
            )

    # -- 内部処理 ------------------------------------------------------------

    def _can_skip(self, existing: dict[str, Any] | None, input_hash: str) -> bool:
        if not existing:
            return False
        return (
            existing.get("contentHash") == input_hash
            and existing.get("processingVersion") == self._settings.processing_version
            and existing.get("processingStatus") == ProcessingStatus.succeeded.value
        )

    def _fetch_original(self, article: NormalizedArticle, metrics: dict[str, Any]) -> ExtractedPage | None:
        if not self._settings.fetch.allow_article_fetch:
            return None
        try:
            result = self._fetch_fn(
                article.normalized_url,
                self._settings.fetch,
                allowed_content_types=("text/html", "application/xhtml+xml"),
            )
        except FetchError as exc:
            metrics["originalFetchError"] = exc.category
            log_warning(
                "article.original_fetch_failed",
                host=urlsplit(article.normalized_url).hostname,
                errorCategory=exc.category,
                statusCode=exc.status_code,
            )
            return None

        metrics["originalFetchMs"] = result.elapsed_ms
        metrics["originalFetchStatus"] = result.status_code
        return extract_page(result.text, result.url)

    def _build_document(
        self,
        article: NormalizedArticle,
        *,
        partition_key: str,
        input_hash: str,
        retry_count: int,
        metrics: dict[str, Any],
    ) -> ArticleDocument:
        page: ExtractedPage | None = None
        needs_fetch = not article.has_sufficient_body or not article.image_urls
        if needs_fetch:
            page = self._fetch_original(article, metrics)

        body_text = article.body_raw or ""
        if page is not None and len(page.text) > len(body_text):
            body_text = page.text

        candidates: list[ImageCandidate] = [
            ImageCandidate(url=url, origin="og" if index == 0 else "content", position=index)
            for index, url in enumerate(article.image_urls)
        ]
        if page is not None:
            candidates.extend(page.images)

        image_assets: list[ImageAsset] = []
        if self._settings.fetch.allow_article_fetch:
            image_processor = ImageProcessor(
                self._blob_store,
                image_settings=self._settings.images,
                fetch_settings=self._settings.fetch,
                container_name=self._settings.storage.images_container,
                fetch_fn=self._fetch_fn,
            )
            image_assets = image_processor.process(
                candidates,
                article_id=article.article_id,
                fallback_alt=article.title[:200],
                source_page=article.normalized_url,
            )
            metrics["imagesDownloaded"] = image_processor.downloaded
            metrics["imagesFailed"] = image_processor.failed

        insights_result = self._generator.generate(article, body_text or article.summary_raw)
        insights = insights_result.insights
        metrics["foundryMs"] = insights_result.duration_ms
        metrics["foundryAttempts"] = insights_result.attempts
        metrics["promptTokens"] = insights_result.prompt_tokens
        metrics["completionTokens"] = insights_result.completion_tokens
        metrics["modelDeployment"] = insights_result.deployment

        content_blob_path = self._archive_body(article.article_id, body_text)
        if content_blob_path:
            metrics["contentArchived"] = True

        for asset in image_assets:
            if not asset.alt_text_ja:
                asset.alt_text_ja = insights.title_ja[:200]

        return ArticleDocument(
            id=article.article_id,
            partition_key=partition_key,
            title=article.title,
            title_ja=insights.title_ja,
            source=article.source,
            author=article.author,
            published_at=article.published_at,
            ingested_at=article.ingested_at or _utcnow(),
            processed_at=_utcnow(),
            original_url=article.normalized_url,
            source_category=article.source_category,
            summary_ja=insights.summary_ja,
            key_points_ja=insights.key_points_ja,
            products=insights.products,
            terms=insights.terms,
            tags=insights.tags,
            category=insights.category,
            update_type=insights.update_type,
            importance=insights.importance,
            importance_rank=IMPORTANCE_RANK.get(insights.importance, 0),
            importance_reason_ja=insights.importance_reason_ja,
            target_audience=insights.target_audience,
            image_assets=image_assets,
            search_keywords=insights.search_keywords,
            search_text=build_search_text(
                article.title,
                insights.title_ja,
                insights.summary_ja,
                insights.key_points_ja,
                insights.products,
                insights.terms,
                insights.tags,
                insights.search_keywords,
                article.source,
                insights.category,
            ),
            raw_blob_path=article.raw_blob_path,
            content_blob_path=content_blob_path,
            content_hash=input_hash,
            model_deployment=insights_result.deployment,
            model_version=insights_result.model_version,
            processing_version=self._settings.processing_version,
            processing_status=ProcessingStatus.succeeded.value,
            last_error=None,
            retry_count=retry_count,
        )

    def _archive_body(self, article_id: str, body_text: str) -> str | None:
        """本文は Cosmos DB ではなく Blob へ保存します。"""
        if not body_text:
            return None
        container = self._settings.storage.content_archive_container
        blob_name = f"{article_id}.txt"
        try:
            self._blob_store.upload(
                container=container,
                blob_name=blob_name,
                data=body_text[:MAX_ARCHIVED_TEXT_CHARS].encode("utf-8"),
                content_type="text/plain; charset=utf-8",
                overwrite=True,
            )
        except Exception as exc:  # noqa: BLE001 - アーカイブ失敗は致命的ではない
            log_warning("article.archive_failed", errorType=type(exc).__name__)
            return None
        return f"{container}/{blob_name}"

    def _archive_failure(self, blob_name: str, raw_bytes: bytes | None, reason: str) -> None:
        container = self._settings.storage.failed_container
        envelope = json.dumps(
            {
                "blobName": blob_name,
                "reason": reason[:1000],
                "recordedAt": _utcnow(),
                "rawBase64Length": len(raw_bytes or b""),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            self._blob_store.upload(
                container=container,
                blob_name=f"{blob_name}.error.json",
                data=envelope,
                content_type="application/json; charset=utf-8",
                overwrite=True,
            )
            if raw_bytes:
                self._blob_store.upload(
                    container=container,
                    blob_name=f"{blob_name}",
                    data=raw_bytes,
                    content_type="application/json; charset=utf-8",
                    overwrite=True,
                )
        except Exception as exc:  # noqa: BLE001 - 退避失敗でも処理結果は変えない
            log_warning("article.failure_archive_failed", errorType=type(exc).__name__)

    def _record_failure(
        self,
        article: NormalizedArticle,
        partition_key: str,
        input_hash: str,
        retry_count: int,
        error: Exception,
        existing: dict[str, Any] | None,
    ) -> None:
        category = getattr(error, "category", "unknown")
        message = f"{type(error).__name__}({category})"
        document = ArticleDocument(
            id=article.article_id,
            partition_key=partition_key,
            title=article.title,
            title_ja=(existing or {}).get("titleJa"),
            source=article.source,
            author=article.author,
            published_at=article.published_at,
            ingested_at=article.ingested_at or _utcnow(),
            processed_at=_utcnow(),
            original_url=article.normalized_url,
            source_category=article.source_category,
            summary_ja=(existing or {}).get("summaryJa"),
            search_text=build_search_text(article.title, article.source),
            raw_blob_path=article.raw_blob_path,
            content_hash=input_hash,
            processing_version=self._settings.processing_version,
            processing_status=ProcessingStatus.failed.value,
            last_error=message,
            retry_count=retry_count + 1,
        )
        try:
            self._repository.upsert_article(document)
            self._repository.record_processing_state(
                article.article_id,
                ProcessingStatus.failed.value,
                retryCount=retry_count + 1,
                lastError=message,
            )
        except Exception as exc:  # noqa: BLE001 - 失敗記録の失敗はログのみ
            log_warning("article.failure_record_failed", errorType=type(exc).__name__)

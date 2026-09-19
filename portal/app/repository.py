"""記事データへのアクセス層。

Cosmos DB 実装とテスト用のインメモリ実装を提供します。
将来 Azure AI Search を採用する場合は :class:`ArticleRepository` の別実装を追加します。
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from collections.abc import Iterable
from typing import Any, Protocol

from app.config import Settings
from app.models import (
    ArticleDetail,
    ArticlePage,
    ArticleQuery,
    ArticleSummary,
    Facets,
    FacetValue,
    ImageView,
)
from app.search import (
    FACET_COUNT_ALIAS,
    FACET_VALUE_ALIAS,
    SUMMARY_PROJECTION,
    build_array_distinct_query,
    build_array_facet_query,
    build_count_query,
    build_document_query,
    build_scalar_distinct_query,
    build_scalar_facet_query,
    build_search_query,
)

logger = logging.getLogger("portal")


class RepositoryUnavailableError(RuntimeError):
    """バックエンドへ接続できない場合のエラー。"""


class ArticleRepository(Protocol):
    """記事の検索・取得インターフェイス。"""

    def search(self, query: ArticleQuery) -> ArticlePage: ...

    def get(self, article_id: str) -> ArticleDetail | None: ...

    def facets(self) -> Facets: ...

    def ping(self) -> bool: ...


# ---------------------------------------------------------------------------
# カーソル
# ---------------------------------------------------------------------------


def encode_cursor(token: str | None) -> str | None:
    if not token:
        return None
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def decode_offset(cursor: str | None) -> int:
    """カーソルをオフセット (0 以上の整数) として解釈します。

    デコードできない場合や数値でない場合は 0 (先頭ページ) を返します。
    """
    token = decode_cursor(cursor)
    if not token:
        return 0
    try:
        return max(int(token), 0)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# マッピング
# ---------------------------------------------------------------------------


def _media_url(blob_path: str | None, images_container: str) -> str | None:
    """画像 Blob パスを Portal 経由の配信 URL へ変換します。"""
    if not blob_path:
        return None
    prefix = f"{images_container}/"
    if not blob_path.startswith(prefix):
        return None
    relative = blob_path[len(prefix) :].strip("/")
    if not relative or ".." in relative:
        return None
    return f"/media/{relative}"


def _to_image_view(raw: dict[str, Any], images_container: str, fallback_alt: str) -> ImageView | None:
    src = _media_url(raw.get("blobPath"), images_container)
    if not src:
        return None
    return ImageView(
        src=src,
        source_url=raw.get("sourceUrl"),
        alt=(raw.get("altTextJa") or fallback_alt or "記事の関連画像")[:300],
        caption=raw.get("captionJa"),
        width=raw.get("width"),
        height=raw.get("height"),
        role=raw.get("role") or "figure",
    )


def _image_views(document: dict[str, Any], images_container: str) -> list[ImageView]:
    fallback = document.get("titleJa") or document.get("title") or ""
    assets = document.get("imageAssets") or []
    views: list[ImageView] = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        view = _to_image_view(raw, images_container, fallback)
        if view is not None:
            views.append(view)
    views.sort(key=lambda item: 0 if item.role == "hero" else 1)
    return views


def to_summary(document: dict[str, Any], images_container: str) -> ArticleSummary:
    images = _image_views(document, images_container)
    return ArticleSummary(
        id=document.get("id", ""),
        title=document.get("title", ""),
        title_ja=document.get("titleJa"),
        summary_ja=document.get("summaryJa"),
        source=document.get("source", ""),
        published_at=document.get("publishedAt", ""),
        original_url=document.get("originalUrl", ""),
        category=document.get("category"),
        importance=document.get("importance"),
        update_type=document.get("updateType"),
        products=list(document.get("products") or [])[:6],
        tags=list(document.get("tags") or [])[:8],
        hero_image=images[0] if images else None,
    )


def to_detail(document: dict[str, Any], images_container: str) -> ArticleDetail:
    images = _image_views(document, images_container)
    return ArticleDetail(
        id=document.get("id", ""),
        title=document.get("title", ""),
        title_ja=document.get("titleJa"),
        summary_ja=document.get("summaryJa"),
        source=document.get("source", ""),
        author=document.get("author"),
        published_at=document.get("publishedAt", ""),
        processed_at=document.get("processedAt"),
        original_url=document.get("originalUrl", ""),
        category=document.get("category"),
        source_category=document.get("sourceCategory"),
        importance=document.get("importance"),
        importance_reason_ja=document.get("importanceReasonJa"),
        update_type=document.get("updateType"),
        products=list(document.get("products") or []),
        tags=list(document.get("tags") or []),
        terms=list(document.get("terms") or []),
        target_audience=list(document.get("targetAudience") or []),
        key_points_ja=list(document.get("keyPointsJa") or []),
        images=images[:3],
        hero_image=images[0] if images else None,
    )


# ---------------------------------------------------------------------------
# Cosmos DB 実装
# ---------------------------------------------------------------------------


class CosmosArticleRepository:
    """Cosmos DB for NoSQL をバックエンドとするリポジトリ。"""

    def __init__(self, settings: Settings, credential: Any, *, client: Any = None) -> None:
        self._settings = settings
        if client is None:
            from azure.cosmos import CosmosClient

            client = CosmosClient(url=settings.cosmos_endpoint, credential=credential)
        self._client = client
        self._container = client.get_database_client(settings.cosmos_database).get_container_client(
            settings.cosmos_articles_container
        )
        self._facets_cache: tuple[float, Facets] | None = None

    def search(self, query: ArticleQuery) -> ArticlePage:
        offset = decode_offset(query.cursor)
        # 次ページの有無を判定するため 1 件多く取得します。
        sql, parameters = build_search_query(
            query,
            projection=SUMMARY_PROJECTION,
            offset=offset,
            limit=query.page_size + 1,
        )
        documents = list(
            self._container.query_items(
                query=sql,
                parameters=parameters,
                max_item_count=query.page_size + 1,
                enable_cross_partition_query=True,
            )
        )
        has_more = len(documents) > query.page_size
        window = documents[: query.page_size]
        items = [to_summary(document, self._settings.images_container) for document in window]
        return ArticlePage(
            items=items,
            next_cursor=encode_cursor(str(offset + len(items))) if has_more else None,
        )

    def count(self, query: ArticleQuery) -> int:
        sql, parameters = build_count_query(query)
        results = list(
            self._container.query_items(
                query=sql,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )
        return int(results[0]) if results else 0

    def get(self, article_id: str) -> ArticleDetail | None:
        sql, parameters = build_document_query(article_id)
        results = list(
            self._container.query_items(
                query=sql,
                parameters=parameters,
                max_item_count=1,
                enable_cross_partition_query=True,
            )
        )
        if not results:
            return None
        return to_detail(results[0], self._settings.images_container)

    def facets(self) -> Facets:
        now = time.monotonic()
        if self._facets_cache and now - self._facets_cache[0] < self._settings.facets_cache_seconds:
            return self._facets_cache[1]

        facets = Facets(
            products=self._facet(build_array_facet_query("products"), build_array_distinct_query("products")),
            tags=self._facet(build_array_facet_query("tags"), build_array_distinct_query("tags")),
            categories=self._facet(build_scalar_facet_query("category"), build_scalar_distinct_query("category")),
            sources=self._facet(build_scalar_facet_query("source"), build_scalar_distinct_query("source")),
            importances=self._facet(
                build_scalar_facet_query("importance"), build_scalar_distinct_query("importance")
            ),
        )
        self._facets_cache = (now, facets)
        return facets

    def _facet(self, grouped_sql: str, distinct_sql: str, *, limit: int = 60) -> list[FacetValue]:
        """件数付きファセットを取得し、失敗した場合は件数なしの候補一覧へフォールバックします。"""
        values: list[FacetValue] = []
        try:
            values = self._grouped_facet(grouped_sql)
        except Exception as exc:  # noqa: BLE001 - 1 項目の失敗で他のフィルターを空にしない
            logger.warning("grouped facet query failed (%s): %s", type(exc).__name__, grouped_sql)

        if not values:
            try:
                values = self._distinct_facet(distinct_sql)
            except Exception as exc:  # noqa: BLE001
                logger.warning("distinct facet query failed (%s): %s", type(exc).__name__, distinct_sql)
                return []

        values.sort(key=lambda item: (-(item.count or 0), item.value))
        return values[:limit]

    def _grouped_facet(self, sql: str) -> list[FacetValue]:
        rows: Iterable[dict[str, Any]] = self._container.query_items(
            query=sql,
            enable_cross_partition_query=True,
        )
        values: list[FacetValue] = []
        for row in rows:
            value = row.get(FACET_VALUE_ALIAS) if isinstance(row, dict) else row
            if not value:
                continue
            count = row.get(FACET_COUNT_ALIAS) if isinstance(row, dict) else None
            values.append(FacetValue(value=str(value), count=count))
        return values

    def _distinct_facet(self, sql: str) -> list[FacetValue]:
        rows: Iterable[Any] = self._container.query_items(
            query=sql,
            enable_cross_partition_query=True,
        )
        values: list[FacetValue] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, str) or not row:
                continue
            if row in seen:
                continue
            seen.add(row)
            values.append(FacetValue(value=row, count=None))
        values.sort(key=lambda item: item.value)
        return values

    def ping(self) -> bool:
        list(
            self._container.query_items(
                query="SELECT VALUE 1",
                max_item_count=1,
                enable_cross_partition_query=True,
            )
        )
        return True


# ---------------------------------------------------------------------------
# インメモリ実装 (テスト / オフライン開発用)
# ---------------------------------------------------------------------------


class InMemoryArticleRepository:
    """テストとオフライン開発のためのインメモリ実装。"""

    def __init__(self, documents: list[dict[str, Any]], images_container: str = "article-images") -> None:
        self._documents = sorted(documents, key=lambda d: d.get("publishedAt", ""), reverse=True)
        self._images_container = images_container

    def _matches(self, document: dict[str, Any], query: ArticleQuery) -> bool:
        if document.get("processingStatus") != "succeeded":
            return False
        if query.categories and document.get("category") not in query.categories:
            return False
        if query.importances and document.get("importance") not in query.importances:
            return False
        if query.sources and document.get("source") not in query.sources:
            return False
        if query.products and not set(query.products) & set(document.get("products") or []):
            return False
        if query.tags and not set(query.tags) & set(document.get("tags") or []):
            return False
        published = document.get("publishedAt", "")
        if query.published_from and published < f"{query.published_from.isoformat()}T00:00:00Z":
            return False
        if query.published_to and published > f"{query.published_to.isoformat()}T23:59:59Z":
            return False
        if query.q:
            term = query.q.lower()
            haystack = " ".join(
                [
                    document.get("searchText", ""),
                    *(document.get("products") or []),
                    *(document.get("tags") or []),
                    *(document.get("terms") or []),
                    *(document.get("searchKeywords") or []),
                ]
            ).lower()
            if term not in haystack:
                return False
        return True

    def search(self, query: ArticleQuery) -> ArticlePage:
        matched = [d for d in self._documents if self._matches(d, query)]
        offset = decode_offset(query.cursor)
        window = matched[offset : offset + query.page_size]
        next_offset = offset + len(window)
        return ArticlePage(
            items=[to_summary(document, self._images_container) for document in window],
            next_cursor=encode_cursor(str(next_offset)) if next_offset < len(matched) else None,
            total_estimate=len(matched),
        )

    def count(self, query: ArticleQuery) -> int:
        return len([d for d in self._documents if self._matches(d, query)])

    def get(self, article_id: str) -> ArticleDetail | None:
        for document in self._documents:
            if document.get("id") == article_id:
                return to_detail(document, self._images_container)
        return None

    def facets(self) -> Facets:
        succeeded = [d for d in self._documents if d.get("processingStatus") == "succeeded"]

        def scalar(field: str) -> list[FacetValue]:
            counter: dict[str, int] = {}
            for document in succeeded:
                value = document.get(field)
                if value:
                    counter[str(value)] = counter.get(str(value), 0) + 1
            return [FacetValue(value=k, count=v) for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]

        def array(field: str) -> list[FacetValue]:
            counter: dict[str, int] = {}
            for document in succeeded:
                for value in document.get(field) or []:
                    counter[str(value)] = counter.get(str(value), 0) + 1
            return [FacetValue(value=k, count=v) for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]

        return Facets(
            products=array("products"),
            tags=array("tags"),
            categories=scalar("category"),
            sources=scalar("source"),
            importances=scalar("importance"),
        )

    def ping(self) -> bool:
        return True

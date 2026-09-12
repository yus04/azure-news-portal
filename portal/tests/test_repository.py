"""リポジトリのマッピングとページングのテスト。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.config import Settings
from app.media import is_safe_blob_path
from app.models import ArticleQuery
from app.repository import CosmosArticleRepository, decode_cursor, encode_cursor, to_detail, to_summary


class TestCursor:
    def test_round_trip(self) -> None:
        assert decode_cursor(encode_cursor("token+value/=")) == "token+value/="

    def test_invalid_cursor_returns_none(self) -> None:
        assert decode_cursor("!!!not-base64!!!") is None
        assert decode_cursor(None) is None


class TestMapping:
    def test_maps_summary_fields(self, documents) -> None:
        summary = to_summary(documents[0], "article-images")

        assert summary.display_title.startswith("Microsoft Foundry")
        assert summary.importance_label == "重要"
        assert summary.update_type_label == "プレビュー"
        assert summary.published_display.startswith("2026年09月02日")
        assert summary.hero_image is not None
        assert summary.hero_image.src.startswith("/media/")
        assert summary.hero_image.alt

    def test_missing_images_yield_none(self, documents) -> None:
        summary = to_summary(documents[1], "article-images")
        assert summary.hero_image is None

    def test_external_blob_paths_are_rejected(self) -> None:
        document = {
            "id": "x",
            "title": "t",
            "source": "s",
            "publishedAt": "2026-01-01T00:00:00Z",
            "originalUrl": "https://example.com",
            "imageAssets": [{"sourceUrl": "https://evil.example/x.png", "blobPath": "other-container/x.png"}],
        }
        assert to_summary(document, "article-images").hero_image is None

    def test_detail_limits_images_to_three(self, documents) -> None:
        document = dict(documents[0])
        document["imageAssets"] = [dict(documents[0]["imageAssets"][0]) for _ in range(6)]
        for index, asset in enumerate(document["imageAssets"]):
            asset["blobPath"] = f"article-images/x/{index}.png"
        assert len(to_detail(document, "article-images").images) == 3

    def test_detail_includes_key_points_and_terms(self, documents) -> None:
        detail = to_detail(documents[0], "article-images")
        assert detail.key_points_ja
        assert detail.terms
        assert detail.importance_reason_ja


class TestInMemoryRepository:
    def test_returns_articles_ordered_by_published_desc(self, repository) -> None:
        page = repository.search(ArticleQuery(page_size=10))
        published = [item.published_at for item in page.items]
        assert published == sorted(published, reverse=True)

    def test_pagination_uses_cursor(self, repository) -> None:
        first = repository.search(ArticleQuery(page_size=2))
        assert len(first.items) == 2
        assert first.next_cursor

        second = repository.search(ArticleQuery(page_size=2, cursor=first.next_cursor))
        assert len(second.items) == 2
        assert {item.id for item in first.items}.isdisjoint({item.id for item in second.items})

    def test_last_page_has_no_cursor(self, repository) -> None:
        page = repository.search(ArticleQuery(page_size=50))
        assert page.next_cursor is None

    def test_filters_by_product(self, repository) -> None:
        page = repository.search(ArticleQuery(products=["Azure Container Apps"]))
        assert page.items
        assert all("Azure Container Apps" in item.products for item in page.items)

    def test_filters_by_importance_and_category(self, repository) -> None:
        page = repository.search(ArticleQuery(importances=["critical"]))
        assert {item.importance for item in page.items} == {"critical"}

    def test_filters_by_date_range(self, repository) -> None:
        page = repository.search(ArticleQuery(published_from=date(2026, 8, 1), published_to=date(2026, 8, 31)))
        assert page.items
        assert all(item.published_at.startswith("2026-08") for item in page.items)

    def test_search_matches_japanese_and_english(self, repository) -> None:
        assert repository.search(ArticleQuery(q="サーバーレス")).items
        assert repository.search(ArticleQuery(q="observability")).items
        assert repository.search(ArticleQuery(q="存在しないキーワード")).items == []

    def test_get_returns_detail(self, repository, documents) -> None:
        detail = repository.get(documents[0]["id"])
        assert detail is not None
        assert detail.id == documents[0]["id"]

    def test_get_returns_none_for_unknown_id(self, repository) -> None:
        assert repository.get("does-not-exist") is None

    def test_facets_are_aggregated(self, repository) -> None:
        facets = repository.facets()
        assert any(item.value == "Azure Container Apps" for item in facets.products)
        assert any(item.value == "Azure Updates" for item in facets.sources)
        assert facets.categories


def _cosmos_repository(container: MagicMock) -> CosmosArticleRepository:
    database = MagicMock()
    database.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = database
    return CosmosArticleRepository(Settings(), credential=MagicMock(), client=client)


def _document(index: int) -> dict:
    return {
        "id": f"id{index}",
        "title": f"title {index}",
        "source": "Azure Updates",
        "publishedAt": f"2026-09-{index + 1:02d}T00:00:00Z",
        "originalUrl": "https://example.com",
    }


class TestCosmosArticleRepository:
    def test_search_enables_cross_partition_query(self) -> None:
        container = MagicMock()
        container.query_items.return_value = []
        repository = _cosmos_repository(container)

        repository.search(ArticleQuery())

        assert container.query_items.call_args.kwargs["enable_cross_partition_query"] is True

    def test_search_uses_offset_limit_paging(self) -> None:
        container = MagicMock()
        container.query_items.return_value = [_document(i) for i in range(3)]
        repository = _cosmos_repository(container)

        page = repository.search(ArticleQuery(page_size=2))

        sql = container.query_items.call_args.kwargs["query"]
        assert "OFFSET 0 LIMIT 3" in sql
        assert len(page.items) == 2
        assert page.next_cursor
        assert decode_cursor(page.next_cursor) == "2"

    def test_search_continues_from_cursor(self) -> None:
        container = MagicMock()
        container.query_items.return_value = [_document(i) for i in range(2)]
        repository = _cosmos_repository(container)

        page = repository.search(ArticleQuery(page_size=2, cursor=encode_cursor("2")))

        assert "OFFSET 2 LIMIT 3" in container.query_items.call_args.kwargs["query"]
        assert len(page.items) == 2
        assert page.next_cursor is None

    def test_facets_read_aliased_columns(self) -> None:
        container = MagicMock()
        container.query_items.return_value = [
            {"facetValue": "Azure Container Apps", "facetCount": 3},
            {"facetValue": "Azure Storage", "facetCount": 5},
        ]
        repository = _cosmos_repository(container)

        facets = repository.facets()

        assert [item.value for item in facets.products] == ["Azure Storage", "Azure Container Apps"]
        assert facets.categories and facets.sources


class TestMediaPathSafety:
    def test_accepts_expected_paths(self) -> None:
        assert is_safe_blob_path("abc123/00-deadbeef.png") is True

    def test_rejects_traversal_and_absolute_paths(self) -> None:
        for path in ["../secret.png", "/etc/passwd", "a//b.png", "", "a/../../b.png"]:
            assert is_safe_blob_path(path) is False

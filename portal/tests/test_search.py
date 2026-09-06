"""検索クエリ生成とフィルター条件のテスト。"""

from __future__ import annotations

from datetime import date

import pytest
from app.models import ArticleQuery
from app.search import (
    build_array_facet_query,
    build_count_query,
    build_document_query,
    build_scalar_facet_query,
    build_search_query,
)


def parameter_values(parameters: list[dict]) -> list:
    return [item["value"] for item in parameters]


class TestBuildSearchQuery:
    def test_defaults_to_succeeded_articles_ordered_by_date(self) -> None:
        sql, parameters = build_search_query(ArticleQuery())

        assert "c.processingStatus = @p1" in sql
        assert sql.endswith("ORDER BY c.publishedAt DESC")
        assert parameter_values(parameters) == ["succeeded"]

    def test_adds_product_filter(self) -> None:
        sql, parameters = build_search_query(ArticleQuery(products=["Azure Container Apps"]))

        assert "ARRAY_CONTAINS(c.products, @p2)" in sql
        assert "Azure Container Apps" in parameter_values(parameters)

    def test_combines_multiple_products_with_or(self) -> None:
        sql, _ = build_search_query(ArticleQuery(products=["A", "B"]))
        assert "(ARRAY_CONTAINS(c.products, @p2) OR ARRAY_CONTAINS(c.products, @p3))" in sql

    def test_adds_category_importance_source_filters(self) -> None:
        query = ArticleQuery(categories=["新機能"], importances=["high"], sources=["Azure Updates"])
        sql, parameters = build_search_query(query)

        assert "c.category IN (@p2)" in sql
        assert "c.importance IN (@p3)" in sql
        assert "c.source IN (@p4)" in sql
        assert "新機能" in parameter_values(parameters)

    def test_adds_date_range(self) -> None:
        query = ArticleQuery(published_from=date(2026, 8, 1), published_to=date(2026, 8, 31))
        sql, parameters = build_search_query(query)

        assert "c.publishedAt >= @p2" in sql
        assert "c.publishedAt <= @p3" in sql
        assert "2026-08-01T00:00:00Z" in parameter_values(parameters)
        assert "2026-08-31T23:59:59Z" in parameter_values(parameters)

    def test_adds_full_text_conditions(self) -> None:
        sql, parameters = build_search_query(ArticleQuery(q="Container Apps"))

        assert "CONTAINS(c.searchText, @p2)" in sql
        assert "EXISTS(SELECT VALUE t FROM t IN c.products" in sql
        assert "container apps" in parameter_values(parameters)

    def test_parameterizes_potentially_malicious_input(self) -> None:
        sql, parameters = build_search_query(ArticleQuery(q="' OR 1=1 --"))

        assert "OR 1=1" not in sql
        assert "' or 1=1 --" in parameter_values(parameters)

    def test_count_query_has_no_order_by(self) -> None:
        sql, _ = build_count_query(ArticleQuery(q="gpu"))
        assert sql.startswith("SELECT VALUE COUNT(1)")
        assert "ORDER BY" not in sql

    def test_document_query_is_parameterized(self) -> None:
        sql, parameters = build_document_query("abc")
        assert sql == "SELECT * FROM c WHERE c.id = @id"
        assert parameters == [{"name": "@id", "value": "abc"}]


class TestFacetQueries:
    def test_scalar_facet(self) -> None:
        sql = build_scalar_facet_query("category")
        assert "GROUP BY c.category" in sql

    def test_array_facet(self) -> None:
        sql = build_array_facet_query("products")
        assert "JOIN v IN c.products" in sql

    @pytest.mark.parametrize("field", ["searchText", "id", "'; DROP"])
    def test_rejects_unknown_fields(self, field: str) -> None:
        with pytest.raises(ValueError):
            build_scalar_facet_query(field)
        with pytest.raises(ValueError):
            build_array_facet_query(field)


class TestArticleQueryValidation:
    def test_trims_and_limits_query_text(self) -> None:
        query = ArticleQuery(q="  " + "a" * 500 + "  ")
        assert query.q is not None and len(query.q) == 200

    def test_deduplicates_and_limits_filters(self) -> None:
        query = ArticleQuery(products=["A", "A", "B"] + [f"P{i}" for i in range(20)])
        assert query.products[:2] == ["A", "B"]
        assert len(query.products) <= 10

    def test_rejects_oversized_page_size(self) -> None:
        with pytest.raises(ValueError):
            ArticleQuery(page_size=500)

    def test_is_filtered_flag(self) -> None:
        assert ArticleQuery().is_filtered is False
        assert ArticleQuery(q="x").is_filtered is True
        assert ArticleQuery(tags=["t"]).is_filtered is True

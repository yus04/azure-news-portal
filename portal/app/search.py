"""Cosmos DB 用のクエリ生成。

将来 Azure AI Search へ移行できるよう、クエリ生成はリポジトリ実装から分離しています。
"""

from __future__ import annotations

from typing import Any

from app.models import ArticleQuery

#: 一覧表示に必要な最小限の射影。
SUMMARY_PROJECTION = (
    "c.id, c.partitionKey, c.title, c.titleJa, c.summaryJa, c.source, c.publishedAt, "
    "c.originalUrl, c.category, c.importance, c.updateType, c.products, c.tags, c.imageAssets"
)

#: 検索対象の配列フィールド。
_ARRAY_SEARCH_FIELDS = ("products", "terms", "tags", "searchKeywords")


class QueryBuilder:
    """パラメーター付き SQL を組み立てるヘルパー。"""

    def __init__(self) -> None:
        self._conditions: list[str] = []
        self._parameters: list[dict[str, Any]] = []
        self._counter = 0

    def _next_name(self) -> str:
        self._counter += 1
        return f"@p{self._counter}"

    def add_parameter(self, value: Any) -> str:
        name = self._next_name()
        self._parameters.append({"name": name, "value": value})
        return name

    def add_condition(self, condition: str) -> None:
        self._conditions.append(condition)

    def add_equals(self, field: str, value: Any) -> None:
        self.add_condition(f"c.{field} = {self.add_parameter(value)}")

    def add_in(self, field: str, values: list[str]) -> None:
        if not values:
            return
        names = [self.add_parameter(value) for value in values]
        self.add_condition(f"c.{field} IN ({', '.join(names)})")

    def add_array_contains_any(self, field: str, values: list[str]) -> None:
        if not values:
            return
        clauses = [f"ARRAY_CONTAINS(c.{field}, {self.add_parameter(value)})" for value in values]
        self.add_condition("(" + " OR ".join(clauses) + ")")

    @property
    def where_clause(self) -> str:
        return " AND ".join(self._conditions) if self._conditions else "true"

    @property
    def parameters(self) -> list[dict[str, Any]]:
        return list(self._parameters)


def _apply_filters(builder: QueryBuilder, query: ArticleQuery) -> None:
    builder.add_equals("processingStatus", "succeeded")
    builder.add_array_contains_any("products", query.products)
    builder.add_array_contains_any("tags", query.tags)
    builder.add_in("category", query.categories)
    builder.add_in("importance", query.importances)
    builder.add_in("source", query.sources)

    if query.published_from:
        name = builder.add_parameter(f"{query.published_from.isoformat()}T00:00:00Z")
        builder.add_condition(f"c.publishedAt >= {name}")
    if query.published_to:
        name = builder.add_parameter(f"{query.published_to.isoformat()}T23:59:59Z")
        builder.add_condition(f"c.publishedAt <= {name}")

    if query.q:
        term = query.q.strip().lower()
        text_name = builder.add_parameter(term)
        clauses = [f"CONTAINS(c.searchText, {text_name})"]
        for field in _ARRAY_SEARCH_FIELDS:
            clauses.append(
                f"EXISTS(SELECT VALUE t FROM t IN c.{field} WHERE CONTAINS(LOWER(t), {text_name}))"
            )
        builder.add_condition("(" + " OR ".join(clauses) + ")")


def build_search_query(
    query: ArticleQuery,
    *,
    projection: str = SUMMARY_PROJECTION,
    offset: int | None = None,
    limit: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """検索・フィルター条件から Cosmos DB の SQL を生成します。

    ``offset`` と ``limit`` を指定すると OFFSET ... LIMIT 句を付与します。
    Cosmos DB の Python SDK はクロスパーティションの ORDER BY クエリで
    継続トークンを利用できないため、ページングはこの方式で行います。
    """
    builder = QueryBuilder()
    _apply_filters(builder, query)
    sql = f"SELECT {projection} FROM c WHERE {builder.where_clause} ORDER BY c.publishedAt DESC"
    if limit is not None:
        sql += f" OFFSET {max(int(offset or 0), 0)} LIMIT {max(int(limit), 1)}"
    return sql, builder.parameters


def build_count_query(query: ArticleQuery) -> tuple[str, list[dict[str, Any]]]:
    """該当件数を取得する SQL を生成します。"""
    builder = QueryBuilder()
    _apply_filters(builder, query)
    return f"SELECT VALUE COUNT(1) FROM c WHERE {builder.where_clause}", builder.parameters


def build_document_query(article_id: str) -> tuple[str, list[dict[str, Any]]]:
    """ID から記事 1 件を取得する SQL を生成します。"""
    return (
        "SELECT * FROM c WHERE c.id = @id",
        [{"name": "@id", "value": article_id}],
    )


def build_scalar_facet_query(field: str) -> str:
    """スカラー項目のファセット (件数付き) を取得する SQL を生成します。

    Cosmos DB では GROUP BY と OFFSET ... LIMIT を併用できないため、
    件数の絞り込みは呼び出し側で行います。また ``value`` / ``count`` は
    予約語のためエイリアスには使用しません。
    """
    if field not in {"category", "source", "importance"}:
        raise ValueError(f"unsupported facet field: {field}")
    return (
        f"SELECT c.{field} AS facetValue, COUNT(1) AS facetCount FROM c "
        f"WHERE c.processingStatus = 'succeeded' AND IS_DEFINED(c.{field}) "
        f"GROUP BY c.{field}"
    )


def build_array_facet_query(field: str) -> str:
    """配列項目のファセットを取得する SQL を生成します。"""
    if field not in {"products", "tags", "terms"}:
        raise ValueError(f"unsupported facet field: {field}")
    return (
        f"SELECT v AS facetValue, COUNT(1) AS facetCount FROM c JOIN v IN c.{field} "
        f"WHERE c.processingStatus = 'succeeded' "
        f"GROUP BY v"
    )

"""API エンドポイントのテスト。"""

from __future__ import annotations

import pytest


class TestHealth:
    def test_healthz(self, client) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readyz(self, client) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


class TestArticlesApi:
    def test_lists_articles(self, client) -> None:
        response = client.get("/api/articles?size=2")
        assert response.status_code == 200

        payload = response.json()
        assert len(payload["items"]) == 2
        assert payload["pageSize"] == 2
        assert payload["nextCursor"]

    def test_pagination_returns_distinct_items(self, client) -> None:
        first = client.get("/api/articles?size=2").json()
        second = client.get(f"/api/articles?size=2&cursor={first['nextCursor']}").json()

        first_ids = {item["id"] for item in first["items"]}
        second_ids = {item["id"] for item in second["items"]}
        assert first_ids.isdisjoint(second_ids)

    def test_filters_by_product(self, client) -> None:
        payload = client.get("/api/articles?product=Azure%20Container%20Apps").json()
        assert payload["items"]
        assert all("Azure Container Apps" in item["products"] for item in payload["items"])

    def test_search_query(self, client) -> None:
        payload = client.get("/api/articles?q=observability").json()
        assert len(payload["items"]) == 1

    @pytest.mark.parametrize("size", ["0", "999", "abc"])
    def test_rejects_invalid_page_size(self, client, size: str) -> None:
        assert client.get(f"/api/articles?size={size}").status_code == 422

    def test_rejects_unknown_parameters_gracefully(self, client) -> None:
        # 未知のクエリパラメーターは無視され 200 を返す
        assert client.get("/api/articles?unknown=1").status_code == 200

    def test_article_detail(self, client, documents) -> None:
        payload = client.get(f"/api/articles/{documents[0]['id']}").json()
        assert payload["id"] == documents[0]["id"]
        assert payload["key_points_ja"]

    def test_unknown_article_returns_404(self, client) -> None:
        assert client.get("/api/articles/" + "f" * 32).status_code == 404

    def test_invalid_article_id_returns_400(self, client) -> None:
        assert client.get("/api/articles/..%2Fetc").status_code in (400, 404)


class TestFiltersApi:
    def test_returns_facets(self, client) -> None:
        payload = client.get("/api/filters").json()
        assert payload["products"]
        assert payload["categories"]
        assert payload["sources"]


class TestSecurityHeaders:
    def test_sets_security_headers(self, client) -> None:
        headers = client.get("/healthz").headers
        assert "Content-Security-Policy" in headers
        assert "script-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"

    def test_openapi_docs_are_disabled(self, client) -> None:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


class TestMedia:
    def test_media_returns_404_when_not_configured(self, client) -> None:
        assert client.get("/media/abc/00-def.png").status_code == 404

"""画面表示 (UI) のテスト。"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.ui


def html_of(client, url: str) -> str:
    response = client.get(url, headers={"Accept": "text/html"})
    assert response.status_code == 200, response.text[:200]
    return response.text


class TestHome:
    def test_renders_home_page(self, client) -> None:
        body = html_of(client, "/")
        assert "Azure News Portal" in body
        assert 'id="article-grid"' in body
        assert 'id="search-input"' in body

    def test_highlights_latest_article(self, client, documents) -> None:
        body = html_of(client, "/")
        latest = max(documents, key=lambda d: d["publishedAt"])

        assert "featured-card" in body
        assert "最新" in body
        featured_section = body.split("card-grid")[0]
        assert latest["titleJa"] in featured_section

    def test_cards_show_source_date_and_products(self, client) -> None:
        body = html_of(client, "/")
        assert "Azure Updates" in body
        assert re.search(r"\d{4}年\d{2}月\d{2}日", body)
        assert "Azure Container Apps" in body

    def test_external_links_are_marked(self, client) -> None:
        body = html_of(client, "/")
        assert 'rel="noopener noreferrer nofollow"' in body
        assert "外部サイト、新しいタブで開きます" in body

    def test_fallback_for_articles_without_image(self, client) -> None:
        body = html_of(client, "/")
        assert "media-fallback" in body

    def test_shows_filter_options(self, client) -> None:
        body = html_of(client, "/")
        assert 'name="product"' in body
        assert 'name="category"' in body
        assert 'name="importance"' in body
        assert 'name="source"' in body
        assert 'name="from"' in body


class TestSearchAndFilters:
    def test_search_shows_only_matching_articles(self, client) -> None:
        body = html_of(client, "/?q=observability")
        assert "検索結果" in body
        assert "Foundry" in body
        assert "サーバーレス GPU が一般提供開始" not in body

    def test_product_filter(self, client) -> None:
        body = html_of(client, "/?product=Azure+Container+Apps")
        assert "サーバーレス GPU" in body
        assert "検索条件を解除" in body

    def test_tag_filter(self, client) -> None:
        body = html_of(client, "/?tag=提供終了")
        assert "クラシックストレージ" in body

    def test_importance_filter(self, client) -> None:
        body = html_of(client, "/?importance=critical")
        assert "最重要" in body

    def test_no_result_state(self, client) -> None:
        body = html_of(client, "/?q=zzzzzzzzzzz")
        assert "見つかりませんでした" in body

    def test_clear_filters_link_present(self, client) -> None:
        body = html_of(client, "/?q=gpu")
        assert 'href="/"' in body


class TestPaging:
    def test_load_more_button_present(self, client) -> None:
        body = html_of(client, "/?size=2")
        assert 'id="load-more"' in body
        assert "data-next-cursor" in body

    def test_partial_returns_cards_only(self, client) -> None:
        first = client.get("/?size=2", headers={"Accept": "text/html"}).text
        cursor = re.search(r'data-next-cursor="([^"]+)"', first).group(1)

        response = client.get(f"/partials/articles?size=2&cursor={cursor}", headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "load-more-marker" in response.text

    def test_last_page_has_no_next_cursor(self, client) -> None:
        response = client.get("/partials/articles?size=50", headers={"Accept": "text/html"})
        assert 'data-next-cursor=""' in response.text


class TestDetail:
    def test_renders_detail_page(self, client, documents) -> None:
        document = documents[0]
        body = html_of(client, f"/articles/{document['id']}")

        assert document["titleJa"] in body
        assert document["title"] in body
        assert document["summaryJa"] in body
        assert document["keyPointsJa"][0] in body
        assert "重要用語" in body
        assert "対象読者" in body
        assert "重要度の理由" in body
        assert document["originalUrl"] in body

    def test_images_have_alt_text(self, client, documents) -> None:
        body = html_of(client, f"/articles/{documents[0]['id']}")
        images = re.findall(r"<img[^>]*>", body)
        assert images
        assert all("alt=" in tag for tag in images)

    def test_detail_partial_for_modal(self, client, documents) -> None:
        response = client.get(f"/partials/articles/{documents[0]['id']}", headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "article-detail" in response.text

    def test_unknown_article_renders_error_page(self, client) -> None:
        response = client.get("/articles/" + "f" * 32, headers={"Accept": "text/html"})
        assert response.status_code == 404
        assert "ページが見つかりません" in response.text


class TestEscaping:
    def test_escapes_html_in_article_fields(self, documents) -> None:
        from app.main import TEMPLATES_DIR
        from app.repository import InMemoryArticleRepository
        from fastapi.templating import Jinja2Templates

        malicious = dict(documents[0])
        malicious["id"] = "b" * 32
        malicious["titleJa"] = "<script>alert('xss')</script>"
        malicious["summaryJa"] = "<img src=x onerror=alert(1)>"

        article = InMemoryArticleRepository([malicious]).get(malicious["id"])
        assert article is not None

        templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        rendered = templates.get_template("partials/article_detail_body.html").render(article=article)

        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered
        assert "<img src=x" not in rendered
        assert "&lt;img src=x onerror=alert(1)&gt;" in rendered

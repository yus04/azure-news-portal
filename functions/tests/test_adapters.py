"""入力 JSON の正規化アダプターのテスト。"""

from __future__ import annotations

from typing import Any

import pytest
from newsproc.adapters import normalize_input, parse_datetime, strip_html
from newsproc.models import NormalizationError


class TestParseDatetime:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-08-28T09:00:00Z", "2026-08-28T09:00:00Z"),
            ("2026-08-28T09:00:00+00:00", "2026-08-28T09:00:00Z"),
            ("2026-08-28T18:00:00+09:00", "2026-08-28T09:00:00Z"),
            ("Fri, 21 Aug 2026 02:30:00 GMT", "2026-08-21T02:30:00Z"),
            ("2026-08-28", "2026-08-28T00:00:00Z"),
        ],
    )
    def test_parses_supported_formats(self, raw: str, expected: str) -> None:
        assert parse_datetime(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "not a date", "yesterday"])
    def test_returns_none_for_unparsable(self, raw: Any) -> None:
        assert parse_datetime(raw) is None


class TestStripHtml:
    def test_removes_tags_and_scripts(self) -> None:
        html = "<p>本文<script>alert('x')</script>です</p><br/>次の行"
        result = strip_html(html)
        assert "alert" not in result
        assert "本文" in result and "次の行" in result

    def test_returns_none_for_empty(self) -> None:
        assert strip_html("") is None
        assert strip_html(None) is None


class TestNormalizeInput:
    def test_normalizes_standard_payload(self, sample_input: dict[str, Any]) -> None:
        article = normalize_input(sample_input, raw_blob_path="raw-articles/a.json")

        assert article.title.startswith("Generally Available")
        assert article.normalized_url == "https://azure.microsoft.com/en-us/updates/serverless-gpus-ga"
        assert article.source == "Azure Updates"
        assert article.published_at == "2026-08-28T09:00:00Z"
        assert article.author == "Azure Container Apps Team"
        assert article.source_category == "Compute"
        assert article.image_urls == ["https://azure.microsoft.com/assets/hero-gpu.png"]
        assert article.raw_blob_path == "raw-articles/a.json"
        assert len(article.article_id) == 32

    def test_supports_alternative_field_names(self) -> None:
        payload = {
            "headline": "Retirement notice",
            "canonicalUrl": "https://azure.microsoft.com/updates/retire",
            "feedName": "Azure Updates",
            "datePublished": "Fri, 21 Aug 2026 02:30:00 GMT",
            "articleBody": "Body text",
            "media": [{"url": "https://azure.microsoft.com/a.png"}],
        }
        article = normalize_input(payload)
        assert article.title == "Retirement notice"
        assert article.published_at == "2026-08-21T02:30:00Z"
        assert article.body_raw == "Body text"
        assert article.image_urls == ["https://azure.microsoft.com/a.png"]

    def test_unwraps_envelope(self) -> None:
        payload = {
            "entry": {
                "name": "Wrapped article",
                "url": "https://example.com/post",
                "isoDate": "2026-09-02T15:20:00+00:00",
                "siteName": "Blog",
            }
        }
        article = normalize_input(payload)
        assert article.title == "Wrapped article"
        assert article.source == "Blog"

    def test_derives_source_from_host_when_missing(self) -> None:
        payload = {
            "title": "No source",
            "url": "https://www.example.com/post",
            "publishedAt": "2026-09-02T00:00:00Z",
        }
        assert normalize_input(payload).source == "example.com"

    def test_resolves_relative_image_urls(self) -> None:
        payload = {
            "title": "Relative image",
            "url": "https://example.com/posts/one",
            "publishedAt": "2026-09-02T00:00:00Z",
            "image": "/assets/pic.png",
        }
        assert normalize_input(payload).image_urls == ["https://example.com/assets/pic.png"]

    @pytest.mark.parametrize(
        ("payload", "missing"),
        [
            ({"url": "https://example.com/a", "publishedAt": "2026-01-01T00:00:00Z"}, "title"),
            ({"title": "t", "publishedAt": "2026-01-01T00:00:00Z"}, "url"),
            ({"title": "t", "url": "https://example.com/a"}, "publishedAt"),
        ],
    )
    def test_raises_for_missing_required_fields(self, payload: dict[str, Any], missing: str) -> None:
        with pytest.raises(NormalizationError) as exc_info:
            normalize_input(payload)
        assert missing in exc_info.value.missing_fields

    def test_raises_for_non_object_payload(self) -> None:
        with pytest.raises(NormalizationError):
            normalize_input([1, 2, 3])

    def test_raises_for_unsupported_url_scheme(self) -> None:
        payload = {"title": "t", "url": "ftp://example.com/a", "publishedAt": "2026-01-01T00:00:00Z"}
        with pytest.raises(NormalizationError):
            normalize_input(payload)

    def test_has_sufficient_body(self, sample_input: dict[str, Any]) -> None:
        short = normalize_input(sample_input)
        assert short.has_sufficient_body is False

        sample_input["content"] = "<p>" + ("長い本文。" * 200) + "</p>"
        assert normalize_input(sample_input).has_sufficient_body is True

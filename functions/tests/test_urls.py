"""URL 正規化・記事 ID 生成・SSRF 対策のテスト。"""

from __future__ import annotations

import pytest
from newsproc.urls import (
    UnsafeUrlError,
    check_public_http_url,
    content_hash,
    ensure_public_http_url,
    normalize_url,
    stable_article_id,
)


class TestNormalizeUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://Azure.Microsoft.com/en-us/updates/", "https://azure.microsoft.com/en-us/updates"),
            ("https://azure.microsoft.com:443/a/b", "https://azure.microsoft.com/a/b"),
            ("http://example.com:80/x?b=2&a=1", "http://example.com/x?a=1&b=2"),
            ("https://example.com/x#section", "https://example.com/x"),
            ("https://example.com", "https://example.com/"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert normalize_url(raw) == expected

    def test_removes_tracking_parameters(self) -> None:
        url = "https://example.com/post?utm_source=rss&utm_medium=feed&id=42&WT.mc_id=abc"
        assert normalize_url(url) == "https://example.com/post?id=42"

    @pytest.mark.parametrize("raw", ["", "   ", "ftp://example.com/x", "https:///nohost"])
    def test_rejects_invalid(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_url(raw)


class TestStableArticleId:
    def test_is_stable_across_equivalent_urls(self) -> None:
        first = stable_article_id("https://Azure.microsoft.com/updates/x/?utm_source=rss")
        second = stable_article_id("https://azure.microsoft.com/updates/x")
        assert first == second
        assert len(first) == 32

    def test_differs_for_different_urls(self) -> None:
        assert stable_article_id("https://example.com/a") != stable_article_id("https://example.com/b")


class TestContentHash:
    def test_same_inputs_produce_same_hash(self) -> None:
        assert content_hash("a", "b", None) == content_hash("a", "b", None)

    def test_field_boundaries_are_respected(self) -> None:
        assert content_hash("ab", "c") != content_hash("a", "bc")


class TestSsrfGuard:
    @pytest.mark.parametrize(
        "address",
        ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "172.16.0.1", "::1", "0.0.0.0"],
    )
    def test_blocks_internal_addresses(self, address: str) -> None:
        result = check_public_http_url("https://internal.example/", resolver=lambda host: [address])
        assert result.allowed is False

    def test_blocks_ipv4_mapped_loopback(self) -> None:
        result = check_public_http_url("https://x.example/", resolver=lambda host: ["::ffff:127.0.0.1"])
        assert result.allowed is False

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com", "https://localhost/x"])
    def test_blocks_dangerous_schemes_and_hosts(self, url: str) -> None:
        assert check_public_http_url(url, resolver=lambda host: ["93.184.216.34"]).allowed is False

    def test_blocks_non_standard_ports(self) -> None:
        result = check_public_http_url("https://example.com:8443/x", resolver=lambda host: ["93.184.216.34"])
        assert result.allowed is False

    def test_allows_public_address(self) -> None:
        result = check_public_http_url("https://azure.microsoft.com/x", resolver=lambda host: ["93.184.216.34"])
        assert result.allowed is True
        assert result.resolved_ips == ("93.184.216.34",)

    def test_ensure_raises_for_unsafe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("newsproc.urls._resolve", lambda host: ["127.0.0.1"])
        with pytest.raises(UnsafeUrlError):
            ensure_public_http_url("https://evil.example/")

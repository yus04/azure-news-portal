"""入力 Blob の JSON を内部の正規化モデルへ変換するアダプター。

入力 JSON の項目名は確定していないため、複数の別名を許容します。
必須項目が欠落する場合は推測で補完せず :class:`NormalizationError` を送出します。
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from newsproc.models import NormalizationError, NormalizedArticle
from newsproc.urls import normalize_url, stable_article_id

#: 内部フィールド名 -> 入力 JSON で許容する別名。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "articleId", "article_id", "guid", "uid", "uuid", "identifier"),
    "title": ("title", "headline", "name", "subject"),
    "url": (
        "url",
        "originalUrl",
        "original_url",
        "link",
        "canonicalUrl",
        "canonical_url",
        "permalink",
        "articleUrl",
        "article_url",
        "webUrl",
    ),
    "source": (
        "source",
        "sourceName",
        "source_name",
        "feed",
        "feedName",
        "feed_name",
        "siteName",
        "site_name",
        "publisher",
        "provider",
    ),
    "published_at": (
        "publishedAt",
        "published_at",
        "published",
        "pubDate",
        "pub_date",
        "datePublished",
        "date_published",
        "publishDate",
        "date",
        "isoDate",
    ),
    "ingested_at": (
        "ingestedAt",
        "ingested_at",
        "fetchedAt",
        "fetched_at",
        "collectedAt",
        "crawledAt",
        "retrievedAt",
    ),
    "summary": (
        "summary",
        "description",
        "excerpt",
        "abstract",
        "snippet",
        "contentSnippet",
        "content_snippet",
        "summaryText",
    ),
    "body": (
        "content",
        "body",
        "contentHtml",
        "content_html",
        "contentEncoded",
        "content:encoded",
        "articleBody",
        "article_body",
        "fullText",
        "full_text",
        "text",
    ),
    "category": (
        "category",
        "sourceCategory",
        "source_category",
        "section",
        "categories",
        "topic",
        "topics",
    ),
    "author": ("author", "authors", "creator", "byline", "dc:creator"),
    "images": (
        "images",
        "image",
        "imageUrl",
        "image_url",
        "imageUrls",
        "thumbnail",
        "thumbnailUrl",
        "ogImage",
        "og_image",
        "enclosure",
        "media",
        "mediaContent",
    ),
}

#: 記事本体が入れ子になっている場合に展開するキー。
_ENVELOPE_KEYS = ("article", "item", "entry", "data", "payload", "record")

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t\u3000]+")
_NEWLINES_RE = re.compile(r"\n{3,}")


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload
    for _ in range(3):
        for key in _ENVELOPE_KEYS:
            value = current.get(key)
            if isinstance(value, dict) and len(current) <= 4:
                current = value
                break
        else:
            break
    return current


def _lookup(payload: dict[str, Any], field: str) -> Any:
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for alias in FIELD_ALIASES[field]:
        value = payload.get(alias)
        if value in (None, "", [], {}):
            value = lowered.get(alias.lower())
        if value not in (None, "", [], {}):
            return value
    return None


def strip_html(value: str | None) -> str | None:
    """HTML タグを除去し、テキストのみを返します。"""
    if not value:
        return None
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _NEWLINES_RE.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = text.strip()
    return text or None


def parse_datetime(value: Any) -> str | None:
    """様々な形式の日時を ISO 8601 (UTC, 末尾 Z) へ正規化します。"""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return dt.isoformat().replace("+00:00", "Z")

    text = str(value).strip()
    if not text:
        return None

    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("value", "name", "text", "#text", "title", "label"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _as_text(item)
            if text:
                return text
        return None
    return str(value).strip() or None


def _as_text_list(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, dict):
        text = _as_text(value)
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_as_text_list(item))
        return result
    return []


def _extract_image_urls(payload: dict[str, Any], base_url: str) -> list[str]:
    raw = _lookup(payload, "images")
    candidates: list[str] = []

    def collect(value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, str):
            candidates.append(value.strip())
        elif isinstance(value, dict):
            for key in ("url", "href", "src", "link", "@url", "image"):
                inner = value.get(key)
                if isinstance(inner, str) and inner.strip():
                    candidates.append(inner.strip())
                    return
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(raw)

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        absolute = urljoin(base_url, candidate)
        scheme = urlsplit(absolute).scheme.lower()
        if scheme not in {"http", "https"}:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        result.append(absolute)
    return result[:20]


def _derive_source(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def normalize_input(payload: Any, *, raw_blob_path: str | None = None) -> NormalizedArticle:
    """入力 JSON を :class:`NormalizedArticle` へ変換します。"""
    if not isinstance(payload, dict):
        raise NormalizationError("input payload must be a JSON object")

    body = _unwrap(payload)
    missing: list[str] = []

    title = _as_text(_lookup(body, "title"))
    if not title:
        missing.append("title")

    url = _as_text(_lookup(body, "url"))
    if not url:
        missing.append("url")

    published_raw = _lookup(body, "published_at")
    published_at = parse_datetime(published_raw)
    if not published_at:
        missing.append("publishedAt")

    if missing:
        raise NormalizationError(
            f"required fields are missing or invalid: {', '.join(missing)}",
            missing_fields=missing,
        )

    assert title is not None and url is not None and published_at is not None

    try:
        normalized_url = normalize_url(url)
    except ValueError as exc:
        raise NormalizationError(f"invalid original url: {exc}", missing_fields=["url"]) from exc

    source = _as_text(_lookup(body, "source")) or _derive_source(normalized_url)
    if not source:
        raise NormalizationError("source could not be determined", missing_fields=["source"])

    authors = _as_text_list(_lookup(body, "author"))
    categories = _as_text_list(_lookup(body, "category"))

    return NormalizedArticle(
        article_id=stable_article_id(normalized_url),
        original_url=url,
        normalized_url=normalized_url,
        title=strip_html(title) or title,
        source=source,
        author=", ".join(authors[:3]) if authors else None,
        published_at=published_at,
        ingested_at=parse_datetime(_lookup(body, "ingested_at")),
        source_category=categories[0] if categories else None,
        summary_raw=strip_html(_as_text(_lookup(body, "summary"))),
        body_raw=strip_html(_as_text(_lookup(body, "body"))),
        image_urls=_extract_image_urls(body, normalized_url),
        raw_blob_path=raw_blob_path,
    )


def known_alias_names() -> Iterable[str]:
    """サポートしている入力項目名の一覧 (ドキュメント用)。"""
    for aliases in FIELD_ALIASES.values():
        yield from aliases

"""外部 HTML の安全な解析、本文抽出、画像候補抽出。

取得した HTML は信頼できない入力として扱い、スクリプトや危険な要素を除去してから解析します。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

#: 解析前に丸ごと削除する要素。
DANGEROUS_TAGS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "object",
    "embed",
    "applet",
    "form",
    "input",
    "button",
    "svg",
    "canvas",
    "template",
    "meta[http-equiv]",
)

#: 本文らしさの低い領域。
BOILERPLATE_SELECTORS = (
    "nav",
    "header",
    "footer",
    "aside",
    "[role=navigation]",
    "[role=banner]",
    "[role=contentinfo]",
)

#: 本文を含む可能性が高い要素の候補 (優先順)。
CONTENT_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    ".article-content",
    ".post-content",
    ".entry-content",
    "#main-content",
    ".content",
)

_WHITESPACE_RE = re.compile(r"[ \t\u3000]+")
_NEWLINES_RE = re.compile(r"\n{3,}")


@dataclass
class ImageCandidate:
    """記事内で見つかった画像の候補。"""

    url: str
    alt: str = ""
    title: str = ""
    width: int | None = None
    height: int | None = None
    origin: str = "content"  # og | twitter | content | link
    position: int = 0


@dataclass
class ExtractedPage:
    """外部ページから抽出した情報。"""

    title: str | None = None
    description: str | None = None
    text: str = ""
    images: list[ImageCandidate] = field(default_factory=list)
    canonical_url: str | None = None
    published_at: str | None = None

    @property
    def text_length(self) -> int:
        return len(self.text)


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"\s*(\d+)", str(value))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def sanitize_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """スクリプトなどの危険な要素と、すべてのイベントハンドラー属性を除去します。"""
    for selector in DANGEROUS_TAGS:
        for node in soup.select(selector):
            node.decompose()
    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        for attr in list(node.attrs):
            lowered = attr.lower()
            if lowered.startswith("on") or lowered in {"srcdoc", "formaction"}:
                del node.attrs[attr]
            elif lowered in {"href", "src", "xlink:href"}:
                value = str(node.attrs.get(attr, "")).strip().lower()
                if value.startswith(("javascript:", "vbscript:", "data:text/html")):
                    del node.attrs[attr]
    return soup


def _meta_content(soup: BeautifulSoup, *keys: str) -> str | None:
    for key in keys:
        for attr in ("property", "name", "itemprop"):
            node = soup.find("meta", attrs={attr: key})
            if isinstance(node, Tag):
                content = node.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    return None


def _absolute(base_url: str, value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    absolute = urljoin(base_url, value.strip())
    if urlsplit(absolute).scheme.lower() not in {"http", "https"}:
        return None
    return absolute


def _collect_text(node: Tag) -> str:
    for tag in node.find_all(["figcaption", "table"]):
        tag.decompose()
    blocks: list[str] = []
    for element in node.find_all(["p", "li", "h2", "h3", "h4", "blockquote", "pre"]):
        text = element.get_text(" ", strip=True)
        if text and len(text) > 1:
            blocks.append(text)
    if not blocks:
        blocks = [node.get_text(" ", strip=True)]
    text = "\n\n".join(blocks)
    text = _WHITESPACE_RE.sub(" ", text)
    return _NEWLINES_RE.sub("\n\n", text).strip()


def _pick_content_node(soup: BeautifulSoup) -> Tag | None:
    best: Tag | None = None
    best_length = 0
    for selector in CONTENT_SELECTORS:
        for node in soup.select(selector):
            if not isinstance(node, Tag):
                continue
            length = len(node.get_text(" ", strip=True))
            if length > best_length:
                best, best_length = node, length
    if best is not None and best_length >= 400:
        return best

    for node in soup.find_all("div"):
        if not isinstance(node, Tag):
            continue
        paragraphs = node.find_all("p", recursive=False) or node.find_all("p")
        if len(paragraphs) < 3:
            continue
        length = sum(len(p.get_text(" ", strip=True)) for p in paragraphs)
        if length > best_length:
            best, best_length = node, length
    return best


def _collect_images(soup: BeautifulSoup, base_url: str, content_node: Tag | None) -> list[ImageCandidate]:
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()

    def add(url: str | None, *, origin: str, alt: str = "", title: str = "", width=None, height=None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append(
            ImageCandidate(
                url=url,
                alt=(alt or "").strip()[:300],
                title=(title or "").strip()[:300],
                width=_to_int(width),
                height=_to_int(height),
                origin=origin,
                position=len(candidates),
            )
        )

    add(_absolute(base_url, _meta_content(soup, "og:image", "og:image:url")), origin="og")
    add(_absolute(base_url, _meta_content(soup, "twitter:image", "twitter:image:src")), origin="twitter")

    scope: Tag | BeautifulSoup = content_node if content_node is not None else soup
    for img in scope.find_all("img"):
        if not isinstance(img, Tag):
            continue
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src and img.get("srcset"):
            src = str(img.get("srcset")).split(",")[0].strip().split(" ")[0]
        add(
            _absolute(base_url, src if isinstance(src, str) else None),
            origin="content",
            alt=str(img.get("alt") or ""),
            title=str(img.get("title") or ""),
            width=img.get("width"),
            height=img.get("height"),
        )

    for source in scope.find_all("source"):
        if not isinstance(source, Tag):
            continue
        srcset = source.get("srcset")
        if isinstance(srcset, str) and srcset.strip():
            add(_absolute(base_url, srcset.split(",")[0].strip().split(" ")[0]), origin="content")

    return candidates[:40]


def extract_page(html_text: str, base_url: str) -> ExtractedPage:
    """HTML から本文、メタデータ、画像候補を抽出します。"""
    soup = BeautifulSoup(html_text or "", "html.parser")
    sanitize_soup(soup)

    canonical = None
    canonical_node = soup.find("link", attrs={"rel": "canonical"})
    if isinstance(canonical_node, Tag):
        canonical = _absolute(base_url, str(canonical_node.get("href") or ""))

    title = _meta_content(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    description = _meta_content(soup, "og:description", "twitter:description", "description")
    published = _meta_content(soup, "article:published_time", "datePublished", "pubdate")

    content_node = _pick_content_node(soup)
    images = _collect_images(soup, base_url, content_node)

    for selector in BOILERPLATE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    if content_node is not None and content_node.decomposed:
        content_node = _pick_content_node(soup)

    text_source = content_node if content_node is not None else soup.body or soup
    text = _collect_text(text_source) if text_source is not None else ""

    return ExtractedPage(
        title=title,
        description=description,
        text=text[:200_000],
        images=images,
        canonical_url=canonical,
        published_at=published,
    )

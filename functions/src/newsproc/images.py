"""記事画像の候補選別、取得、処理済みコンテナーへの保存。"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from newsportal_shared.article import ImageAsset, ImageRole

from newsproc.config import FetchSettings, ImageSettings
from newsproc.fetcher import FetchError, fetch_url
from newsproc.htmlx import ImageCandidate
from newsproc.logging_utils import log_warning

#: 除外する URL / alt のパターン (ロゴ、アイコン、広告、トラッキングなど)。
EXCLUDE_PATTERNS = re.compile(
    r"(logo|avatar|gravatar|profile-?pic|icon|favicon|sprite|badge|button|banner-?ad|"
    r"/ads?/|doubleclick|adservice|tracking|tracker|beacon|pixel|analytics|spacer|blank\.gif|"
    r"1x1|transparent|placeholder|emoji|social-?share|rss|feed-?icon)",
    re.IGNORECASE,
)

#: 図表として重要度が高いことを示すパターン。
DIAGRAM_PATTERNS = re.compile(
    r"(architecture|diagram|topology|flow|screenshot|portal|dashboard|chart|graph|overview|figure|fig\d)",
    re.IGNORECASE,
)

#: 拡張子から Content-Type を推定するためのマップ。
_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass
class ScoredImage:
    candidate: ImageCandidate
    score: float
    role: str


def _has_disallowed_extension(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith((".svg", ".ico", ".bmp", ".tif", ".tiff"))


def score_candidate(candidate: ImageCandidate, settings: ImageSettings) -> ScoredImage | None:
    """画像候補にスコアを付けます。除外対象の場合は None を返します。"""
    haystack = f"{candidate.url} {candidate.alt} {candidate.title}"
    if EXCLUDE_PATTERNS.search(haystack):
        return None
    if _has_disallowed_extension(candidate.url):
        return None

    width, height = candidate.width, candidate.height
    if width is not None and height is not None:
        if width < settings.min_width or height < settings.min_height:
            return None
        if width * height < settings.min_area:
            return None
        if width <= 4 or height <= 4:
            return None

    score = 0.0
    role = ImageRole.figure.value

    if candidate.origin == "og":
        score += 100.0
        role = ImageRole.hero.value
    elif candidate.origin == "twitter":
        score += 80.0
        role = ImageRole.hero.value
    else:
        score += max(0.0, 40.0 - candidate.position * 2.0)

    if DIAGRAM_PATTERNS.search(haystack):
        score += 35.0
        if role == ImageRole.figure.value:
            role = ImageRole.diagram.value

    if candidate.alt:
        score += min(len(candidate.alt), 60) / 4.0

    if width is not None and height is not None:
        area = width * height
        score += min(area / 40_000.0, 25.0)
        ratio = width / height if height else 0
        if 1.2 <= ratio <= 2.4:
            score += 10.0

    return ScoredImage(candidate=candidate, score=score, role=role)


def select_image_candidates(
    candidates: list[ImageCandidate],
    settings: ImageSettings,
    *,
    limit: int | None = None,
) -> list[ScoredImage]:
    """記事理解に有用な画像候補を、スコア順に重複排除して返します。"""
    max_count = limit if limit is not None else settings.max_images
    scored: list[ScoredImage] = []
    seen_urls: set[str] = set()

    for candidate in candidates:
        normalized = candidate.url.split("?")[0].rstrip("/").lower()
        if normalized in seen_urls:
            continue
        result = score_candidate(candidate, settings)
        if result is None:
            continue
        seen_urls.add(normalized)
        scored.append(result)

    scored.sort(key=lambda item: item.score, reverse=True)
    # ダウンロード失敗に備えて上限より多めに候補を残します。
    return scored[: max(max_count * 3, max_count)]


def _probe_image(data: bytes) -> tuple[int, int, str] | None:
    """Pillow で画像サイズと形式を取得します。取得できない場合は None。"""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow は requirements に含まれる
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            fmt = (image.format or "").lower()
        return width, height, fmt
    except Exception:  # noqa: BLE001 - 壊れた画像は候補から外すだけ
        return None


def _blob_name(article_id: str, index: int, checksum: str, content_type: str) -> str:
    extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower(), ".img")
    return f"{article_id}/{index:02d}-{checksum[:12]}{extension}"


class ImageProcessor:
    """画像候補をダウンロードし、処理済み画像コンテナーへ保存します。"""

    def __init__(
        self,
        blob_store,
        *,
        image_settings: ImageSettings,
        fetch_settings: FetchSettings,
        container_name: str,
        fetch_fn=fetch_url,
    ) -> None:
        self._blob_store = blob_store
        self._image_settings = image_settings
        self._fetch_settings = fetch_settings
        self._container_name = container_name
        self._fetch_fn = fetch_fn
        self.downloaded = 0
        self.failed = 0

    def process(
        self,
        candidates: list[ImageCandidate],
        *,
        article_id: str,
        fallback_alt: str,
        source_page: str,
    ) -> list[ImageAsset]:
        selected = select_image_candidates(candidates, self._image_settings)
        assets: list[ImageAsset] = []
        checksums: set[str] = set()

        for scored in selected:
            if len(assets) >= self._image_settings.max_images:
                break
            asset = self._process_one(
                scored,
                article_id=article_id,
                index=len(assets),
                fallback_alt=fallback_alt,
                source_page=source_page,
                checksums=checksums,
            )
            if asset is not None:
                assets.append(asset)
        return assets

    def _process_one(
        self,
        scored: ScoredImage,
        *,
        article_id: str,
        index: int,
        fallback_alt: str,
        source_page: str,
        checksums: set[str],
    ) -> ImageAsset | None:
        url = scored.candidate.url
        try:
            result = self._fetch_fn(
                url,
                self._fetch_settings,
                accept="image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
                allowed_content_types=self._image_settings.allowed_content_types,
                max_bytes=self._image_settings.max_bytes,
            )
        except FetchError as exc:
            self.failed += 1
            log_warning("image.fetch.failed", imageHost=urlsplit(url).hostname, errorCategory=exc.category)
            return None

        if result.truncated:
            self.failed += 1
            log_warning("image.skipped", reason="truncated", imageHost=urlsplit(url).hostname)
            return None

        probe = _probe_image(result.content)
        if probe is None:
            self.failed += 1
            log_warning("image.skipped", reason="undecodable", imageHost=urlsplit(url).hostname)
            return None

        width, height, _fmt = probe
        settings = self._image_settings
        if width < settings.min_width or height < settings.min_height or width * height < settings.min_area:
            log_warning("image.skipped", reason="too_small", width=width, height=height)
            return None

        checksum = hashlib.sha256(result.content).hexdigest()
        if checksum in checksums:
            log_warning("image.skipped", reason="duplicate")
            return None
        checksums.add(checksum)

        content_type = result.content_type.split(";")[0].strip().lower()
        blob_name = _blob_name(article_id, index, checksum, content_type)
        try:
            self._blob_store.upload(
                container=self._container_name,
                blob_name=blob_name,
                data=result.content,
                content_type=content_type,
                overwrite=True,
            )
        except Exception as exc:  # noqa: BLE001 - 1 枚の失敗で記事処理を止めない
            self.failed += 1
            log_warning("image.upload.failed", errorType=type(exc).__name__)
            return None

        self.downloaded += 1
        alt = (scored.candidate.alt or scored.candidate.title or fallback_alt).strip()
        return ImageAsset(
            source_url=url,
            blob_path=f"{self._container_name}/{blob_name}",
            content_type=content_type,
            width=width,
            height=height,
            size_bytes=len(result.content),
            checksum=checksum,
            role=scored.role,
            alt_text_ja=alt[:300] or fallback_alt,
            caption_ja=(scored.candidate.title or None),
            source_page=source_page,
        )

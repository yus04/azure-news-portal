"""Cosmos DB に保存する記事ドキュメントのスキーマ。

Python 側は snake_case、Cosmos DB 側は camelCase を使用します。
シリアライズ時は必ず ``model_dump(mode="json", by_alias=True)`` を使用してください。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class Importance(str, Enum):
    """記事の重要度。"""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


#: ソート用の数値ランク。値が大きいほど重要。
IMPORTANCE_RANK: dict[str, int] = {
    Importance.critical.value: 4,
    Importance.high.value: 3,
    Importance.medium.value: 2,
    Importance.low.value: 1,
}


class UpdateType(str, Enum):
    """記事が扱う更新の種別。"""

    ga = "ga"
    preview = "preview"
    update = "update"
    deprecation = "deprecation"
    retirement = "retirement"
    security = "security"
    pricing = "pricing"
    guidance = "guidance"
    event = "event"
    other = "other"


class ProcessingStatus(str, Enum):
    """パイプラインの処理状態。"""

    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    skipped = "skipped"


class ImageRole(str, Enum):
    """画像の役割。"""

    hero = "hero"
    figure = "figure"
    diagram = "diagram"
    screenshot = "screenshot"
    chart = "chart"


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class ImageAsset(CamelModel):
    """記事に紐づく画像 1 枚分のメタデータ。"""

    source_url: str = Field(description="元サイト上の画像 URL")
    blob_path: str | None = Field(default=None, description="処理済み画像 Blob のパス (container/name)")
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    checksum: str | None = Field(default=None, description="画像バイト列の SHA-256")
    role: str = Field(default=ImageRole.figure.value)
    alt_text_ja: str | None = Field(default=None, description="日本語の代替テキスト")
    caption_ja: str | None = None
    source_page: str | None = Field(default=None, description="画像を検出したページ URL")


class ArticleDocument(CamelModel):
    """Cosmos DB `articles` コンテナーのドキュメント。"""

    id: str
    partition_key: str

    # --- 原文由来 ---
    title: str
    source: str
    author: str | None = None
    published_at: str = Field(description="ISO 8601 (UTC) の公開日時")
    ingested_at: str | None = None
    processed_at: str | None = None
    original_url: str
    source_category: str | None = None

    # --- 生成結果 ---
    title_ja: str | None = None
    summary_ja: str | None = None
    key_points_ja: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    update_type: str | None = None
    importance: str | None = None
    importance_rank: int = 0
    importance_reason_ja: str | None = None
    target_audience: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    search_text: str = ""

    # --- 参照 ---
    image_assets: list[ImageAsset] = Field(default_factory=list)
    raw_blob_path: str | None = None
    content_blob_path: str | None = Field(
        default=None, description="抽出本文アーカイブの Blob パス。Cosmos には本文を保存しない。"
    )

    # --- 処理メタデータ ---
    content_hash: str = ""
    model_deployment: str | None = None
    model_version: str | None = None
    processing_version: str = "0.0.0"
    processing_status: str = ProcessingStatus.pending.value
    last_error: str | None = None
    retry_count: int = 0
    schema_version: int = 1

    @field_validator("published_at", "ingested_at", "processed_at", mode="before")
    @classmethod
    def _coerce_datetime(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value

    def to_cosmos_dict(self) -> dict[str, Any]:
        """Cosmos DB へ書き込む dict を返します。"""
        return self.model_dump(mode="json", by_alias=True, exclude_none=False)


def build_partition_key(published_at: str | None) -> str:
    """公開日時 (ISO 8601) から ``YYYY-MM`` 形式のパーティションキーを生成します。

    日時が不明な場合は ``unknown`` を返します。
    """
    if not published_at:
        return "unknown"
    try:
        normalized = published_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def build_search_text(*parts: Any) -> str:
    """検索用の小文字連結テキストを生成します。"""
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            chunks.extend(str(item) for item in part if item)
        else:
            chunks.append(str(part))
    joined = " ".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())
    return joined.lower()[:8000]

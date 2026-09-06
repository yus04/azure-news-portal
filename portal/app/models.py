"""Portal が扱うビューモデルと検索条件。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from newsportal_shared.article import IMPORTANCE_RANK
from pydantic import BaseModel, ConfigDict, Field, field_validator

#: 重要度の日本語ラベル。
IMPORTANCE_LABELS: dict[str, str] = {
    "critical": "最重要",
    "high": "重要",
    "medium": "標準",
    "low": "参考",
}

#: 更新種別の日本語ラベル。
UPDATE_TYPE_LABELS: dict[str, str] = {
    "ga": "一般提供",
    "preview": "プレビュー",
    "update": "更新",
    "deprecation": "非推奨",
    "retirement": "提供終了",
    "security": "セキュリティ",
    "pricing": "価格",
    "guidance": "ガイダンス",
    "event": "イベント",
    "other": "その他",
}


class ImageView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    src: str | None = None
    source_url: str | None = None
    alt: str = ""
    caption: str | None = None
    width: int | None = None
    height: int | None = None
    role: str = "figure"


class ArticleSummary(BaseModel):
    """カード表示に必要な項目。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    title_ja: str | None = None
    summary_ja: str | None = None
    source: str
    published_at: str
    original_url: str
    category: str | None = None
    importance: str | None = None
    update_type: str | None = None
    products: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    hero_image: ImageView | None = None

    @property
    def display_title(self) -> str:
        return self.title_ja or self.title

    @property
    def importance_label(self) -> str:
        return IMPORTANCE_LABELS.get(self.importance or "", "")

    @property
    def importance_rank(self) -> int:
        return IMPORTANCE_RANK.get(self.importance or "", 0)

    @property
    def update_type_label(self) -> str:
        return UPDATE_TYPE_LABELS.get(self.update_type or "", "")

    @property
    def published_display(self) -> str:
        return format_datetime(self.published_at)


class ArticleDetail(ArticleSummary):
    """記事詳細で表示する項目。"""

    author: str | None = None
    key_points_ja: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)
    importance_reason_ja: str | None = None
    source_category: str | None = None
    images: list[ImageView] = Field(default_factory=list)
    processed_at: str | None = None

    @property
    def processed_display(self) -> str:
        return format_datetime(self.processed_at)


class ArticlePage(BaseModel):
    items: list[ArticleSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    total_estimate: int | None = None


class FacetValue(BaseModel):
    value: str
    count: int | None = None


class Facets(BaseModel):
    products: list[FacetValue] = Field(default_factory=list)
    categories: list[FacetValue] = Field(default_factory=list)
    tags: list[FacetValue] = Field(default_factory=list)
    sources: list[FacetValue] = Field(default_factory=list)
    importances: list[FacetValue] = Field(default_factory=list)


class ArticleQuery(BaseModel):
    """検索・フィルター条件。"""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200)
    products: list[str] = Field(default_factory=list, max_length=10)
    categories: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=10)
    importances: list[str] = Field(default_factory=list, max_length=4)
    sources: list[str] = Field(default_factory=list, max_length=10)
    published_from: date | None = None
    published_to: date | None = None
    page_size: int = Field(default=12, ge=1, le=50)
    cursor: str | None = Field(default=None, max_length=8000)

    @field_validator("q", mode="before")
    @classmethod
    def _clean_query(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return text[:200] or None

    @field_validator("products", "categories", "tags", "importances", "sources", mode="before")
    @classmethod
    def _clean_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in result:
                result.append(text[:100])
        return result[:10]

    @property
    def is_filtered(self) -> bool:
        return bool(
            self.q
            or self.products
            or self.categories
            or self.tags
            or self.importances
            or self.sources
            or self.published_from
            or self.published_to
        )


def format_datetime(value: str | None) -> str:
    """ISO 8601 の日時を日本語表示へ整形します。"""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y年%m月%d日 %H:%M UTC")

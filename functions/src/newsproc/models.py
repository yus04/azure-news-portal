"""Function 内部で使用する正規化モデルとモデル出力スキーマ。"""

from __future__ import annotations

from typing import Any

from newsportal_shared.article import Importance, UpdateType
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalizedArticle(BaseModel):
    """入力 Blob を内部表現へ正規化した記事。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    article_id: str
    original_url: str
    normalized_url: str
    title: str
    source: str
    author: str | None = None
    published_at: str
    ingested_at: str | None = None
    source_category: str | None = None
    summary_raw: str | None = None
    body_raw: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    raw_blob_path: str | None = None

    @property
    def has_sufficient_body(self) -> bool:
        """モデル入力として十分な本文があるかどうか。"""
        body_length = len(self.body_raw or "")
        summary_length = len(self.summary_raw or "")
        return body_length >= 600 or (body_length + summary_length) >= 800


class NormalizationError(ValueError):
    """入力 JSON を正規化できなかった場合のエラー。"""

    def __init__(self, message: str, *, missing_fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields or []


class ArticleInsights(BaseModel):
    """Foundry モデルが生成する構造化出力。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title_ja: str = Field(min_length=1, max_length=200)
    summary_ja: str = Field(min_length=1, max_length=1200)
    key_points_ja: list[str] = Field(min_length=1, max_length=8)
    target_audience: list[str] = Field(default_factory=list, max_length=6)
    products: list[str] = Field(default_factory=list, max_length=12)
    terms: list[str] = Field(default_factory=list, max_length=12)
    tags: list[str] = Field(default_factory=list, max_length=15)
    category: str = Field(min_length=1, max_length=60)
    update_type: str = Field(default=UpdateType.other.value)
    importance: str = Field(default=Importance.medium.value)
    importance_reason_ja: str = Field(default="", max_length=400)
    search_keywords: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("key_points_ja", mode="after")
    @classmethod
    def _trim_key_points(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("key_points_ja must contain at least one item")
        return cleaned[:5]

    @field_validator("update_type", mode="before")
    @classmethod
    def _coerce_update_type(cls, value: Any) -> str:
        allowed = {member.value for member in UpdateType}
        text = str(value or "").strip().lower()
        return text if text in allowed else UpdateType.other.value

    @field_validator("importance", mode="before")
    @classmethod
    def _coerce_importance(cls, value: Any) -> str:
        allowed = {member.value for member in Importance}
        text = str(value or "").strip().lower()
        return text if text in allowed else Importance.medium.value

    @field_validator("products", "terms", "tags", "search_keywords", "target_audience", mode="after")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            text = (item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result


#: モデルへ渡す JSON Schema (structured outputs 用)。
INSIGHTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title_ja",
        "summary_ja",
        "key_points_ja",
        "target_audience",
        "products",
        "terms",
        "tags",
        "category",
        "update_type",
        "importance",
        "importance_reason_ja",
        "search_keywords",
    ],
    "properties": {
        "title_ja": {"type": "string", "description": "自然な日本語のタイトル"},
        "summary_ja": {"type": "string", "description": "2〜4 文の日本語要約"},
        "key_points_ja": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3〜5 個の主な要点",
        },
        "target_audience": {"type": "array", "items": {"type": "string"}},
        "products": {"type": "array", "items": {"type": "string"}},
        "terms": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string"},
        "update_type": {
            "type": "string",
            "enum": [member.value for member in UpdateType],
        },
        "importance": {
            "type": "string",
            "enum": [member.value for member in Importance],
        },
        "importance_reason_ja": {"type": "string"},
        "search_keywords": {"type": "array", "items": {"type": "string"}},
    },
}

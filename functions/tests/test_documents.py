"""共有スキーマと Cosmos DB ドキュメント変換のテスト。"""

from __future__ import annotations

import json

import pytest
from newsportal_shared.article import (
    ArticleDocument,
    ImageAsset,
    ProcessingStatus,
    build_partition_key,
    build_search_text,
)


class TestPartitionKey:
    @pytest.mark.parametrize(
        ("published", "expected"),
        [
            ("2026-08-28T09:00:00Z", "2026-08"),
            ("2026-01-05T23:30:00+09:00", "2026-01"),
            ("2025-12-31T23:00:00-05:00", "2026-01"),
            (None, "unknown"),
            ("not-a-date", "unknown"),
        ],
    )
    def test_builds_month_partition(self, published, expected) -> None:
        assert build_partition_key(published) == expected


class TestSearchText:
    def test_flattens_and_lowercases(self) -> None:
        text = build_search_text("Azure Container Apps", ["GPU", "GA"], None, "  spaced  ")
        assert text == "azure container apps gpu ga spaced"

    def test_limits_length(self) -> None:
        assert len(build_search_text("あ" * 20_000)) <= 8000


class TestArticleDocument:
    def test_serializes_to_camel_case(self) -> None:
        document = ArticleDocument(
            id="a" * 32,
            partition_key="2026-08",
            title="Serverless GPUs GA",
            title_ja="サーバーレス GPU が GA",
            source="Azure Updates",
            published_at="2026-08-28T09:00:00Z",
            original_url="https://azure.microsoft.com/updates/gpu",
            key_points_ja=["要点1"],
            image_assets=[
                ImageAsset(
                    source_url="https://cdn.example.com/a.png",
                    blob_path="article-images/x/00-abc.png",
                    alt_text_ja="図",
                )
            ],
            processing_status=ProcessingStatus.succeeded.value,
        )
        payload = document.to_cosmos_dict()

        assert payload["partitionKey"] == "2026-08"
        assert payload["titleJa"] == "サーバーレス GPU が GA"
        assert payload["keyPointsJa"] == ["要点1"]
        assert payload["imageAssets"][0]["blobPath"] == "article-images/x/00-abc.png"
        assert payload["imageAssets"][0]["altTextJa"] == "図"
        json.dumps(payload, ensure_ascii=False)

    def test_accepts_camel_case_input(self) -> None:
        document = ArticleDocument.model_validate(
            {
                "id": "b" * 32,
                "partitionKey": "2026-09",
                "title": "t",
                "source": "s",
                "publishedAt": "2026-09-01T00:00:00Z",
                "originalUrl": "https://example.com/x",
                "summaryJa": "要約",
            }
        )
        assert document.summary_ja == "要約"
        assert document.partition_key == "2026-09"

    def test_normalizes_datetime_objects(self) -> None:
        from datetime import datetime, timezone

        document = ArticleDocument(
            id="c" * 32,
            partition_key="2026-09",
            title="t",
            source="s",
            published_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
            original_url="https://example.com/x",
        )
        assert document.published_at == "2026-09-01T12:00:00Z"

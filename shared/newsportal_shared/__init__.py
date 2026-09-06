"""Azure News Portal の Functions と Portal が共有するスキーマ定義。

このパッケージが記事ドキュメント (Cosmos DB) の唯一の正となるスキーマ定義です。
Functions / Portal のビルド時に各アプリケーションへコピーされます
(scripts/package-function.sh, portal/Dockerfile を参照)。
"""

from newsportal_shared.article import (
    IMPORTANCE_RANK,
    ArticleDocument,
    ImageAsset,
    ImageRole,
    Importance,
    ProcessingStatus,
    UpdateType,
    build_partition_key,
    build_search_text,
)

__all__ = [
    "ArticleDocument",
    "ImageAsset",
    "ImageRole",
    "Importance",
    "ProcessingStatus",
    "UpdateType",
    "IMPORTANCE_RANK",
    "build_partition_key",
    "build_search_text",
]

__version__ = "1.0.0"

"""実行環境の依存関係を組み立てるファクトリー。"""

from __future__ import annotations

from functools import lru_cache

from newsproc.blobs import BlobStore, get_credential
from newsproc.config import Settings, get_settings
from newsproc.foundry import build_generator
from newsproc.pipeline import ArticlePipeline
from newsproc.repository import ArticleRepository


def build_pipeline(settings: Settings | None = None) -> ArticlePipeline:
    """設定から本番用のパイプラインを構築します。"""
    resolved = settings or get_settings()
    credential = get_credential(resolved.managed_identity_client_id)

    if not resolved.storage.blob_endpoint:
        raise RuntimeError("STORAGE_BLOB_ENDPOINT (または STORAGE_ACCOUNT_NAME) が設定されていません")
    if not resolved.cosmos.endpoint:
        raise RuntimeError("COSMOS_ENDPOINT が設定されていません")
    if not resolved.foundry.endpoint:
        raise RuntimeError("FOUNDRY_ENDPOINT が設定されていません")

    return ArticlePipeline(
        settings=resolved,
        blob_store=BlobStore(resolved.storage.blob_endpoint, credential),
        repository=ArticleRepository(resolved.cosmos, credential),
        generator=build_generator(resolved.foundry, credential),
    )


@lru_cache(maxsize=1)
def get_pipeline() -> ArticlePipeline:
    """プロセス内で共有するパイプラインインスタンスを返します。"""
    return build_pipeline()

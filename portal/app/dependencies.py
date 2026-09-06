"""アプリケーション全体で共有する依存関係の解決。"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.media import MediaStore
from app.repository import ArticleRepository, CosmosArticleRepository, InMemoryArticleRepository

#: オフラインモードで読み込むサンプルデータ。
_OFFLINE_SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "cosmos" / "articles.json"


@lru_cache(maxsize=1)
def get_credential(client_id: str = "") -> Any:
    from azure.identity import DefaultAzureCredential

    if client_id:
        return DefaultAzureCredential(managed_identity_client_id=client_id)
    return DefaultAzureCredential()


def _load_offline_documents() -> list[dict[str, Any]]:
    override = os.environ.get("PORTAL_OFFLINE_DATA", "").strip()
    path = Path(override) if override else _OFFLINE_SAMPLE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_repository() -> ArticleRepository:
    settings: Settings = get_settings()
    if settings.enable_offline_mode or not settings.cosmos_endpoint:
        return InMemoryArticleRepository(_load_offline_documents(), settings.images_container)
    return CosmosArticleRepository(settings, get_credential(settings.managed_identity_client_id))


@lru_cache(maxsize=1)
def get_media_store() -> MediaStore | None:
    settings = get_settings()
    if settings.enable_offline_mode or not settings.storage_blob_endpoint:
        return None
    return MediaStore(
        settings.storage_blob_endpoint,
        settings.images_container,
        get_credential(settings.managed_identity_client_id),
    )


def reset_dependencies() -> None:
    """テストでキャッシュを破棄するためのヘルパー。"""
    get_repository.cache_clear()
    get_media_store.cache_clear()
    get_credential.cache_clear()
    get_settings.cache_clear()

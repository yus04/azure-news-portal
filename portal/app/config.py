"""Azure News Portal の設定。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    return raw in {"1", "true", "yes", "on"} if raw else default


@dataclass(frozen=True)
class Settings:
    cosmos_endpoint: str = ""
    cosmos_database: str = "newsportal"
    cosmos_articles_container: str = "articles"
    storage_blob_endpoint: str = ""
    images_container: str = "article-images"
    managed_identity_client_id: str = ""
    environment: str = "dev"
    default_page_size: int = 12
    max_page_size: int = 50
    facets_cache_seconds: int = 300
    media_cache_seconds: int = 86400
    max_media_bytes: int = 8 * 1024 * 1024
    enable_offline_mode: bool = False
    app_version: str = "1.0.0"

    @property
    def configured(self) -> bool:
        return bool(self.cosmos_endpoint) or self.enable_offline_mode


def load_settings() -> Settings:
    return Settings(
        cosmos_endpoint=_env("COSMOS_ENDPOINT"),
        cosmos_database=_env("COSMOS_DATABASE_NAME", "newsportal"),
        cosmos_articles_container=_env("COSMOS_ARTICLES_CONTAINER", "articles"),
        storage_blob_endpoint=_env("STORAGE_BLOB_ENDPOINT"),
        images_container=_env("IMAGES_CONTAINER_NAME", "article-images"),
        managed_identity_client_id=_env("AZURE_CLIENT_ID"),
        environment=_env("PORTAL_ENVIRONMENT", "dev"),
        default_page_size=_env_int("PORTAL_PAGE_SIZE", 12),
        max_page_size=_env_int("PORTAL_MAX_PAGE_SIZE", 50),
        facets_cache_seconds=_env_int("PORTAL_FACETS_CACHE_SECONDS", 300),
        media_cache_seconds=_env_int("PORTAL_MEDIA_CACHE_SECONDS", 86400),
        max_media_bytes=_env_int("PORTAL_MAX_MEDIA_BYTES", 8 * 1024 * 1024),
        enable_offline_mode=_env_bool("PORTAL_OFFLINE_MODE", False),
        app_version=_env("PORTAL_APP_VERSION", "1.0.0"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()

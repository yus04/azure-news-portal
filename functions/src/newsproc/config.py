"""環境変数から読み込む Function の設定。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class StorageSettings:
    account_name: str = ""
    blob_endpoint: str = ""
    input_container: str = "raw-articles"
    images_container: str = "article-images"
    content_archive_container: str = "article-content"
    failed_container: str = "failed-articles"


@dataclass(frozen=True)
class CosmosSettings:
    endpoint: str = ""
    database_name: str = "newsportal"
    articles_container: str = "articles"
    state_container: str = "processing-state"


@dataclass(frozen=True)
class FoundrySettings:
    endpoint: str = ""
    project_endpoint: str = ""
    deployment: str = "gpt-5-6-luna"
    api_version: str = "2025-04-01-preview"
    api_style: str = "chat"
    reasoning_effort: str = ""
    max_output_tokens: int = 4000
    timeout_seconds: float = 120.0
    max_retries: int = 3
    temperature: float | None = None


@dataclass(frozen=True)
class FetchSettings:
    user_agent: str = (
        "AzureNewsPortalBot/1.0 (+https://learn.microsoft.com/azure; article summarizer)"
    )
    connect_timeout: float = 10.0
    read_timeout: float = 20.0
    max_retries: int = 2
    max_bytes: int = 3 * 1024 * 1024
    max_redirects: int = 3
    allow_article_fetch: bool = True


@dataclass(frozen=True)
class ImageSettings:
    max_images: int = 3
    max_bytes: int = 5 * 1024 * 1024
    min_width: int = 200
    min_height: int = 120
    min_area: int = 40_000
    allowed_content_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    )


@dataclass(frozen=True)
class Settings:
    storage: StorageSettings = field(default_factory=StorageSettings)
    cosmos: CosmosSettings = field(default_factory=CosmosSettings)
    foundry: FoundrySettings = field(default_factory=FoundrySettings)
    fetch: FetchSettings = field(default_factory=FetchSettings)
    images: ImageSettings = field(default_factory=ImageSettings)
    managed_identity_client_id: str = ""
    processing_version: str = "1.0.0"
    max_processing_retries: int = 3


def load_settings() -> Settings:
    """環境変数から Settings を構築します。"""
    blob_endpoint = _env("STORAGE_BLOB_ENDPOINT")
    account_name = _env("STORAGE_ACCOUNT_NAME")
    if not blob_endpoint and account_name:
        blob_endpoint = f"https://{account_name}.blob.core.windows.net/"

    return Settings(
        storage=StorageSettings(
            account_name=account_name,
            blob_endpoint=blob_endpoint,
            input_container=_env("INPUT_CONTAINER_NAME", "raw-articles"),
            images_container=_env("IMAGES_CONTAINER_NAME", "article-images"),
            content_archive_container=_env("CONTENT_ARCHIVE_CONTAINER_NAME", "article-content"),
            failed_container=_env("FAILED_CONTAINER_NAME", "failed-articles"),
        ),
        cosmos=CosmosSettings(
            endpoint=_env("COSMOS_ENDPOINT"),
            database_name=_env("COSMOS_DATABASE_NAME", "newsportal"),
            articles_container=_env("COSMOS_ARTICLES_CONTAINER", "articles"),
            state_container=_env("COSMOS_STATE_CONTAINER", "processing-state"),
        ),
        foundry=FoundrySettings(
            endpoint=_env("FOUNDRY_ENDPOINT"),
            project_endpoint=_env("FOUNDRY_PROJECT_ENDPOINT"),
            deployment=_env("FOUNDRY_MODEL_DEPLOYMENT", "gpt-5-6-luna"),
            api_version=_env("FOUNDRY_API_VERSION", "2025-04-01-preview"),
            api_style=_env("FOUNDRY_API_STYLE", "chat").lower() or "chat",
            reasoning_effort=_env("FOUNDRY_REASONING_EFFORT"),
            max_output_tokens=_env_int("FOUNDRY_MAX_OUTPUT_TOKENS", 4000),
            timeout_seconds=_env_float("FOUNDRY_TIMEOUT_SECONDS", 120.0),
            max_retries=_env_int("FOUNDRY_MAX_RETRIES", 3),
            temperature=(
                _env_float("FOUNDRY_TEMPERATURE", 0.0) if _env("FOUNDRY_TEMPERATURE") else None
            ),
        ),
        fetch=FetchSettings(
            user_agent=_env("ARTICLE_FETCH_USER_AGENT", FetchSettings.user_agent),
            connect_timeout=_env_float("ARTICLE_FETCH_CONNECT_TIMEOUT", 10.0),
            read_timeout=_env_float("ARTICLE_FETCH_READ_TIMEOUT", 20.0),
            max_retries=_env_int("ARTICLE_FETCH_MAX_RETRIES", 2),
            max_bytes=_env_int("ARTICLE_FETCH_MAX_BYTES", 3 * 1024 * 1024),
            max_redirects=_env_int("ARTICLE_FETCH_MAX_REDIRECTS", 3),
            allow_article_fetch=_env_bool("ARTICLE_FETCH_ENABLED", True),
        ),
        images=ImageSettings(
            max_images=_env_int("IMAGE_MAX_COUNT", 3),
            max_bytes=_env_int("IMAGE_MAX_BYTES", 5 * 1024 * 1024),
            min_width=_env_int("IMAGE_MIN_WIDTH", 200),
            min_height=_env_int("IMAGE_MIN_HEIGHT", 120),
            min_area=_env_int("IMAGE_MIN_AREA", 40_000),
        ),
        managed_identity_client_id=_env("AZURE_CLIENT_ID"),
        processing_version=_env("PROCESSING_VERSION", "1.0.0"),
        max_processing_retries=_env_int("MAX_PROCESSING_RETRIES", 3),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()

"""Managed Identity を使用した Blob Storage アクセス。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings


@lru_cache(maxsize=1)
def get_credential(client_id: str = "") -> DefaultAzureCredential:
    """DefaultAzureCredential を取得します (ユーザー割り当て ID に対応)。"""
    if client_id:
        return DefaultAzureCredential(managed_identity_client_id=client_id)
    return DefaultAzureCredential()


class BlobStore:
    """Blob の読み書きを行う薄いラッパー。"""

    def __init__(self, account_url: str, credential: Any) -> None:
        self._client = BlobServiceClient(account_url=account_url, credential=credential)

    def download(self, container: str, blob_name: str, *, max_bytes: int | None = None) -> bytes:
        blob = self._client.get_blob_client(container=container, blob=blob_name)
        stream = blob.download_blob(max_concurrency=1)
        data = stream.readall()
        if max_bytes is not None and len(data) > max_bytes:
            raise ValueError(f"blob exceeds max size: {len(data)} > {max_bytes}")
        return data

    def exists(self, container: str, blob_name: str) -> bool:
        blob = self._client.get_blob_client(container=container, blob=blob_name)
        try:
            blob.get_blob_properties()
        except ResourceNotFoundError:
            return False
        return True

    def upload(
        self,
        *,
        container: str,
        blob_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
        cache_control: str = "public, max-age=86400",
    ) -> str:
        blob = self._client.get_blob_client(container=container, blob=blob_name)
        blob.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=ContentSettings(content_type=content_type, cache_control=cache_control),
        )
        return f"{container}/{blob_name}"

    def list_blob_names(self, container: str, *, name_starts_with: str | None = None):
        container_client = self._client.get_container_client(container)
        for blob in container_client.list_blobs(name_starts_with=name_starts_with):
            yield blob.name

    def close(self) -> None:
        self._client.close()

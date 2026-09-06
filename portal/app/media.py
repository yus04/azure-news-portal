"""処理済み画像 Blob を Portal 経由で配信するためのアクセス層。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from azure.core.exceptions import ResourceNotFoundError

#: 許可する Blob 名 (パストラバーサル防止)。
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")

#: 配信を許可する Content-Type。
ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


class MediaNotFoundError(Exception):
    """要求された画像が存在しない、または配信できない場合のエラー。"""


@dataclass
class MediaObject:
    content: bytes
    content_type: str


def is_safe_blob_path(path: str) -> bool:
    if not path or ".." in path or path.startswith("/") or "//" in path:
        return False
    return bool(_SAFE_PATH_RE.match(path))


class MediaStore:
    """Managed Identity で画像 Blob を読み取ります。"""

    def __init__(self, blob_endpoint: str, container: str, credential: Any, *, client: Any = None) -> None:
        if client is None:
            from azure.storage.blob import BlobServiceClient

            client = BlobServiceClient(account_url=blob_endpoint, credential=credential)
        self._client = client
        self._container = container

    def get(self, blob_path: str, *, max_bytes: int) -> MediaObject:
        if not is_safe_blob_path(blob_path):
            raise MediaNotFoundError("invalid blob path")
        blob = self._client.get_blob_client(container=self._container, blob=blob_path)
        try:
            properties = blob.get_blob_properties()
        except ResourceNotFoundError as exc:
            raise MediaNotFoundError("blob not found") from exc

        size = properties.size or 0
        if size > max_bytes:
            raise MediaNotFoundError("blob too large")

        content_type = (properties.content_settings.content_type or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_MEDIA_TYPES:
            raise MediaNotFoundError(f"content type not allowed: {content_type or '(none)'}")

        data = blob.download_blob(max_concurrency=1).readall()
        return MediaObject(content=data, content_type=content_type)

"""外部 URL からの安全な取得処理。

- SSRF 対策としてリダイレクトを含む全ホップで宛先 IP を検証します。
- 最大取得サイズ、接続 / 読み取りタイムアウト、限定的なリトライを実装します。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from newsproc.config import FetchSettings
from newsproc.logging_utils import log_warning
from newsproc.urls import check_public_http_url


class FetchError(Exception):
    """外部リソースの取得に失敗した場合のエラー。"""

    def __init__(self, message: str, *, category: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    content: bytes
    truncated: bool = False
    elapsed_ms: float = 0.0

    @property
    def text(self) -> str:
        encoding = "utf-8"
        lowered = self.content_type.lower()
        if "charset=" in lowered:
            encoding = lowered.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


def _validate(url: str) -> None:
    result = check_public_http_url(url)
    if not result.allowed:
        raise FetchError(f"blocked url: {result.reason}", category="ssrf")


def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            return b"".join(chunks)[:max_bytes], True
    return b"".join(chunks), False


def fetch_url(
    url: str,
    settings: FetchSettings,
    *,
    accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    allowed_content_types: tuple[str, ...] | None = None,
    max_bytes: int | None = None,
    client: httpx.Client | None = None,
) -> FetchResult:
    """外部 URL を安全に取得します。

    :param allowed_content_types: 許可する Content-Type の接頭辞。None の場合は検証しません。
    """
    limit = max_bytes if max_bytes is not None else settings.max_bytes
    timeout = httpx.Timeout(connect=settings.connect_timeout, read=settings.read_timeout, write=10.0, pool=10.0)
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": accept,
        "Accept-Language": "en,ja;q=0.8",
    }

    owns_client = client is None
    http_client = client or httpx.Client(follow_redirects=False, timeout=timeout, headers=headers)
    started = time.perf_counter()
    try:
        current_url = url
        last_error: FetchError | None = None
        for attempt in range(settings.max_retries + 1):
            try:
                return _fetch_once(
                    http_client,
                    current_url,
                    settings=settings,
                    limit=limit,
                    allowed_content_types=allowed_content_types,
                    started=started,
                )
            except FetchError as exc:
                last_error = exc
                if exc.category not in {"timeout", "network", "http_5xx", "http_429"}:
                    raise
                if attempt >= settings.max_retries:
                    raise
                delay = min(2.0 ** attempt, 8.0)
                log_warning(
                    "fetch.retry",
                    attempt=attempt + 1,
                    delaySeconds=delay,
                    errorCategory=exc.category,
                    host=httpx.URL(current_url).host,
                )
                time.sleep(delay)
        raise last_error or FetchError("fetch failed", category="network")
    finally:
        if owns_client:
            http_client.close()


def _fetch_once(
    client: httpx.Client,
    url: str,
    *,
    settings: FetchSettings,
    limit: int,
    allowed_content_types: tuple[str, ...] | None,
    started: float,
) -> FetchResult:
    current_url = url
    for _ in range(settings.max_redirects + 1):
        _validate(current_url)
        try:
            with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("redirect without location", category="protocol")
                    current_url = str(httpx.URL(current_url).join(location))
                    continue

                status = response.status_code
                if status == 429:
                    raise FetchError("rate limited", category="http_429", status_code=status)
                if 500 <= status < 600:
                    raise FetchError(f"server error {status}", category="http_5xx", status_code=status)
                if status >= 400:
                    raise FetchError(f"client error {status}", category="http_4xx", status_code=status)

                content_type = response.headers.get("content-type", "").strip()
                if allowed_content_types is not None:
                    base_type = content_type.split(";")[0].strip().lower()
                    matched = any(
                        base_type == allowed or base_type.startswith(allowed)
                        for allowed in allowed_content_types
                    )
                    if not matched:
                        raise FetchError(
                            f"unexpected content-type: {base_type or '(none)'}",
                            category="content_type",
                            status_code=status,
                        )

                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise FetchError("content too large", category="too_large", status_code=status)

                content, truncated = _read_capped(response, limit)
                return FetchResult(
                    url=current_url,
                    status_code=status,
                    content_type=content_type,
                    content=content,
                    truncated=truncated,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                )
        except httpx.TimeoutException as exc:
            raise FetchError(f"timeout: {type(exc).__name__}", category="timeout") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"network error: {type(exc).__name__}", category="network") from exc

    raise FetchError("too many redirects", category="protocol")

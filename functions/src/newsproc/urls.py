"""URL の正規化、安定した記事 ID の生成、SSRF 対策のためのホスト検証。"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: 正規化時に除去する計測用クエリパラメーター。
TRACKING_PARAM_PREFIXES = ("utm_", "wt.mc_id", "ocid", "cid", "mc_cid", "mc_eid", "gclid", "fbclid")

#: 許可するスキーム。
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: 許可するポート。
ALLOWED_PORTS = frozenset({80, 443})

#: 明示的に拒否するホスト名。
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.azure.com",
        "instance-data",
    }
)


class UnsafeUrlError(ValueError):
    """SSRF 対策により拒否された URL。"""


@dataclass(frozen=True)
class UrlCheckResult:
    allowed: bool
    reason: str = ""
    resolved_ips: tuple[str, ...] = ()


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return any(lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES)


def normalize_url(url: str) -> str:
    """URL を決定的な形へ正規化します。

    - スキーム / ホストを小文字化
    - 既定ポートを除去
    - フラグメントを除去
    - 計測用クエリパラメーターを除去し、残りをキー順にソート
    - 末尾スラッシュを除去 (ルートを除く)
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty")

    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"unsupported url scheme: {scheme}")

    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise ValueError(f"url has no host: {url}")

    port = parts.port
    if port is not None and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port = None
    netloc = hostname if port is None else f"{hostname}:{port}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking_param(k)]
    query = urlencode(sorted(query_items))

    return urlunsplit((scheme, netloc, path, query, ""))


def stable_article_id(original_url: str) -> str:
    """正規化 URL から再実行しても同じになる記事 ID を生成します。"""
    normalized = normalize_url(original_url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def content_hash(*parts: str | None) -> str:
    """記事内容のハッシュ。差分がある場合のみ再処理するために使用します。"""
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").strip().encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def _resolve(hostname: str) -> list[str]:
    infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if ip.is_loopback:
        return "loopback address"
    if ip.is_private:
        return "private address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_disallowed_ip(ip.ipv4_mapped)
        if ip.is_site_local:
            return "site-local address"
    return ""


def check_public_http_url(url: str, *, resolver=_resolve) -> UrlCheckResult:
    """外部 URL がパブリックインターネット上の安全な宛先かどうかを検証します。

    ローカル / プライベート / リンクローカル / メタデータエンドポイントを拒否します。
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        return UrlCheckResult(False, f"invalid url: {exc}")

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return UrlCheckResult(False, f"scheme not allowed: {scheme or '(none)'}")

    hostname = (parts.hostname or "").lower()
    if not hostname:
        return UrlCheckResult(False, "missing host")
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".localhost") or hostname.endswith(".internal"):
        return UrlCheckResult(False, f"host not allowed: {hostname}")

    port = parts.port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        return UrlCheckResult(False, f"port not allowed: {port}")

    try:
        addresses = resolver(hostname)
    except OSError as exc:
        return UrlCheckResult(False, f"dns resolution failed: {type(exc).__name__}")

    if not addresses:
        return UrlCheckResult(False, "dns resolution returned no address")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return UrlCheckResult(False, f"invalid resolved address: {address}")
        reason = _is_disallowed_ip(ip)
        if reason:
            return UrlCheckResult(False, f"{reason}: {address}")

    return UrlCheckResult(True, resolved_ips=tuple(addresses))


def ensure_public_http_url(url: str) -> tuple[str, ...]:
    """安全でない URL の場合に :class:`UnsafeUrlError` を送出します。"""
    result = check_public_http_url(url)
    if not result.allowed:
        raise UnsafeUrlError(result.reason)
    return result.resolved_ips

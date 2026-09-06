"""構造化ログのユーティリティ。

秘密情報や記事本文をログへ出力しないよう、明示的に許可した値だけを記録します。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_LOGGER_NAME = "newsproc"

#: ログへ出力しないキー (部分一致)。
_REDACT_PATTERNS = re.compile(
    r"(key|secret|token|password|credential|authorization|connectionstring|sas)",
    re.IGNORECASE,
)

#: 1 つの値としてログに残す最大文字数。
_MAX_VALUE_LENGTH = 512


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def _sanitize(key: str, value: Any) -> Any:
    if _REDACT_PATTERNS.search(key):
        return "[redacted]"
    if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
        return value[:_MAX_VALUE_LENGTH] + "...[truncated]"
    if isinstance(value, (list, tuple)):
        return [_sanitize(key, item) for item in value][:50]
    if isinstance(value, dict):
        return {k: _sanitize(k, v) for k, v in value.items()}
    return value


def log_event(level: int, event: str, **fields: Any) -> None:
    """構造化イベントを 1 行の JSON として出力します。"""
    payload: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = _sanitize(key, value)
    get_logger().log(level, json.dumps(payload, ensure_ascii=False, default=str))


def log_info(event: str, **fields: Any) -> None:
    log_event(logging.INFO, event, **fields)


def log_warning(event: str, **fields: Any) -> None:
    log_event(logging.WARNING, event, **fields)


def log_error(event: str, **fields: Any) -> None:
    log_event(logging.ERROR, event, **fields)


@contextmanager
def timed(event: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """処理時間を計測して開始/完了/失敗を記録します。"""
    extra: dict[str, Any] = {}
    started = time.perf_counter()
    log_info(f"{event}.started", **fields)
    try:
        yield extra
    except Exception as exc:  # noqa: BLE001 - ログ後に再送出
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        log_error(
            f"{event}.failed",
            durationMs=elapsed_ms,
            errorType=type(exc).__name__,
            errorMessage=str(exc)[:_MAX_VALUE_LENGTH],
            **fields,
            **extra,
        )
        raise
    else:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        log_info(f"{event}.completed", durationMs=elapsed_ms, **fields, **extra)


def configure_telemetry() -> None:
    """Application Insights (OpenTelemetry) を構成します。

    接続文字列が無い場合や SDK が未導入の場合は何もしません。
    """
    import os

    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    if os.environ.get("NEWSPROC_TELEMETRY_CONFIGURED") == "1":
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(logger_name=_LOGGER_NAME)
        os.environ["NEWSPROC_TELEMETRY_CONFIGURED"] = "1"
    except Exception as exc:  # noqa: BLE001 - テレメトリ失敗で処理を止めない
        get_logger().warning("failed to configure Azure Monitor: %s", type(exc).__name__)

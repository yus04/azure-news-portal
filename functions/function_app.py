"""Azure Functions (Python v2 programming model) のエントリーポイント。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# デプロイパッケージ内の src/ をインポートパスへ追加する。
_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import azure.functions as func  # noqa: E402
from newsproc.bootstrap import get_pipeline  # noqa: E402
from newsproc.logging_utils import configure_telemetry, log_error, log_info  # noqa: E402
from newsproc.pipeline import TransientProcessingError  # noqa: E402

configure_telemetry()

app = func.FunctionApp()


@app.function_name(name="ProcessArticleBlob")
@app.event_grid_trigger(arg_name="event")
def process_article_blob(event: func.EventGridEvent) -> None:
    """入力コンテナーに保存された記事 JSON を処理します。"""
    payload = {
        "id": event.id,
        "eventType": event.event_type,
        "subject": event.subject,
        "eventTime": event.event_time.isoformat() if event.event_time else None,
        "data": event.get_json() if event.get_json() is not None else {},
    }

    log_info("eventgrid.received", eventId=event.id, subject=event.subject, eventType=event.event_type)

    try:
        outcome = get_pipeline().handle_event(payload)
    except TransientProcessingError as exc:
        # 例外を送出して Event Grid の再試行 / デッドレターに委ねる。
        log_error("eventgrid.retry_requested", eventId=event.id, reason=str(exc))
        raise
    except Exception as exc:  # noqa: BLE001 - 想定外エラーも再試行対象にする
        log_error("eventgrid.unhandled_error", eventId=event.id, errorType=type(exc).__name__)
        raise

    log_info(
        "eventgrid.processed",
        eventId=event.id,
        status=outcome.status,
        articleId=outcome.article_id,
        reason=outcome.reason or None,
        metrics=json.dumps(outcome.metrics, ensure_ascii=False, default=str) if outcome.metrics else None,
    )

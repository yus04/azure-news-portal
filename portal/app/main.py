"""Azure News Portal の FastAPI アプリケーション。"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.dependencies import get_media_store, get_repository
from app.media import MediaNotFoundError
from app.models import IMPORTANCE_LABELS, UPDATE_TYPE_LABELS, ArticlePage, ArticleQuery

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

logger = logging.getLogger("portal")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def _configure_telemetry() -> None:
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(logger_name="portal")
    except Exception as exc:  # noqa: BLE001 - テレメトリ失敗でアプリを止めない
        logger.warning("failed to configure Azure Monitor: %s", type(exc).__name__)


def build_query_string(params: dict[str, Any]) -> str:
    """テンプレートからページングリンクを組み立てるためのヘルパー。"""
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((key, str(item)) for item in value if str(item))
        else:
            pairs.append((key, str(value)))
    return urlencode(pairs)


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["build_query_string"] = build_query_string
templates.env.globals["importance_labels"] = IMPORTANCE_LABELS
templates.env.globals["update_type_labels"] = UPDATE_TYPE_LABELS

app = FastAPI(
    title="Azure News Portal",
    description="Azure の最新記事を日本語で要約・分類して閲覧できるポータル",
    version=get_settings().app_version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_configure_telemetry()


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


# ---------------------------------------------------------------------------
# 依存関係
# ---------------------------------------------------------------------------


def query_params(
    settings: Annotated[Settings, Depends(get_settings)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    product: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI の仕様
    category: Annotated[list[str], Query()] = [],  # noqa: B006
    tag: Annotated[list[str], Query()] = [],  # noqa: B006
    importance: Annotated[list[str], Query()] = [],  # noqa: B006
    source: Annotated[list[str], Query()] = [],  # noqa: B006
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    size: Annotated[int | None, Query(ge=1, le=50)] = None,
    cursor: Annotated[str | None, Query(max_length=8000)] = None,
) -> ArticleQuery:
    try:
        return ArticleQuery(
            q=q,
            products=product,
            categories=category,
            tags=tag,
            importances=importance,
            sources=source,
            published_from=date_from,
            published_to=date_to,
            page_size=min(size or settings.default_page_size, settings.max_page_size),
            cursor=cursor,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid query parameters") from exc


def _query_to_params(query: ArticleQuery) -> dict[str, Any]:
    return {
        "q": query.q,
        "product": query.products,
        "category": query.categories,
        "tag": query.tags,
        "importance": query.importances,
        "source": query.sources,
        "from": query.published_from.isoformat() if query.published_from else None,
        "to": query.published_to.isoformat() if query.published_to else None,
        "size": query.page_size,
    }


def _search(query: ArticleQuery) -> ArticlePage:
    try:
        return get_repository().search(query)
    except Exception as exc:  # noqa: BLE001 - バックエンド障害は 503 で返す
        response_headers = getattr(exc, "headers", {})
        logger.exception(
            "article search failed: type=%s status=%s substatus=%s activityId=%s message=%s",
            type(exc).__name__,
            getattr(exc, "status_code", None),
            response_headers.get("x-ms-substatus"),
            response_headers.get("x-ms-activity-id"),
            str(exc),
        )
        raise HTTPException(status_code=503, detail="article store is unavailable") from exc


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, query: Annotated[ArticleQuery, Depends(query_params)]) -> HTMLResponse:
    page = _search(query)
    try:
        facets = get_repository().facets()
    except Exception:  # noqa: BLE001 - ファセット取得失敗でもページは表示する
        logger.warning("facet lookup failed")
        from app.models import Facets

        facets = Facets()

    featured = page.items[0] if page.items and not query.is_filtered else None
    rest = page.items[1:] if featured else page.items

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "featured": featured,
            "articles": rest,
            "facets": facets,
            "query": query,
            "params": _query_to_params(query),
            "next_cursor": page.next_cursor,
            "total_estimate": page.total_estimate,
            "is_filtered": query.is_filtered,
        },
    )


@app.get("/partials/articles", response_class=HTMLResponse)
def articles_partial(request: Request, query: Annotated[ArticleQuery, Depends(query_params)]) -> HTMLResponse:
    page = _search(query)
    return templates.TemplateResponse(
        request,
        "partials/article_list.html",
        {
            "articles": page.items,
            "next_cursor": page.next_cursor,
            "params": _query_to_params(query),
            "is_filtered": query.is_filtered,
        },
    )


@app.get("/articles/{article_id}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: str) -> HTMLResponse:
    article = _get_article_or_404(article_id)
    return templates.TemplateResponse(request, "article_detail.html", {"article": article})


@app.get("/partials/articles/{article_id}", response_class=HTMLResponse)
def article_detail_partial(request: Request, article_id: str) -> HTMLResponse:
    article = _get_article_or_404(article_id)
    return templates.TemplateResponse(request, "partials/article_detail_body.html", {"article": article})


def _get_article_or_404(article_id: str):
    if not article_id or len(article_id) > 128 or not article_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid article id")
    try:
        article = get_repository().get(article_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("article lookup failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="article store is unavailable") from exc
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return article


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/articles")
def api_articles(query: Annotated[ArticleQuery, Depends(query_params)]) -> dict[str, Any]:
    page = _search(query)
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "nextCursor": page.next_cursor,
        "pageSize": query.page_size,
        "totalEstimate": page.total_estimate,
    }


@app.get("/api/articles/{article_id}")
def api_article(article_id: str) -> dict[str, Any]:
    return _get_article_or_404(article_id).model_dump(mode="json")


@app.get("/api/filters")
def api_filters() -> dict[str, Any]:
    try:
        facets = get_repository().facets()
    except Exception as exc:  # noqa: BLE001
        logger.exception("facet lookup failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="article store is unavailable") from exc
    return facets.model_dump(mode="json")


# ---------------------------------------------------------------------------
# 画像配信
# ---------------------------------------------------------------------------


@app.get("/media/{blob_path:path}")
def media(blob_path: str, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    store = get_media_store()
    if store is None:
        raise HTTPException(status_code=404, detail="media is not configured")
    try:
        obj = store.get(blob_path, max_bytes=settings.max_media_bytes)
    except MediaNotFoundError as exc:
        raise HTTPException(status_code=404, detail="image not found") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("media fetch failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="image could not be retrieved") from exc

    return Response(
        content=obj.content,
        media_type=obj.content_type,
        headers={
            "Cache-Control": f"public, max-age={settings.media_cache_seconds}, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# ヘルスチェック
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": get_settings().app_version}


@app.get("/readyz")
def readyz() -> JSONResponse:
    try:
        get_repository().ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness check failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})


# ---------------------------------------------------------------------------
# エラーハンドラー
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html and not request.url.path.startswith(("/api/", "/media/")):
        return templates.TemplateResponse(
            request,
            "error.html",
            {"status_code": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

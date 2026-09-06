# syntax=docker/dockerfile:1
# ビルドコンテキストはリポジトリのルートです (shared/ を含めるため)。
#   docker build -f portal/Dockerfile -t azure-news-portal .
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --- 依存関係 --------------------------------------------------------------
FROM base AS deps
COPY portal/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# --- 実行イメージ ----------------------------------------------------------
FROM base AS runtime

RUN groupadd --system --gid 10001 portal \
    && useradd --system --uid 10001 --gid portal --home-dir /app --shell /usr/sbin/nologin portal

COPY --from=deps /install /usr/local

COPY --chown=portal:portal shared/newsportal_shared /app/newsportal_shared
COPY --chown=portal:portal portal/app /app/app
COPY --chown=portal:portal portal/templates /app/templates
COPY --chown=portal:portal portal/static /app/static

ENV PYTHONPATH=/app \
    PORT=8000

USER portal

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]

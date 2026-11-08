# syntax=docker/dockerfile:1
# One image, two roles: the API (default CMD) and the worker (command: python -m app.worker).

# --- 1. Build the frontend ------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- 2. Python runtime ------------------------------------------------------------------------
FROM python:3.13-slim AS app
# ffmpeg pulls keyframes out of archived videos for Claude to read (Phase 2 deep parsing).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev

COPY --from=web /web/dist /app/static

# Runs as UID 1000: the host directory mounted at /data must be writable by that UID.
RUN useradd --uid 1000 --create-home wander && mkdir -p /data && chown wander:wander /data
USER wander

ENV PATH="/app/.venv/bin:$PATH" \
    WANDER_DATA_DIR=/data \
    WANDER_STATIC_DIR=/app/static

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

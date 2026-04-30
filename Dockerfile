# syntax=docker/dockerfile:1.7

# ============================================================
# Stage 1 — builder: resolve deps + build .venv with uv
# ============================================================
FROM python:3.13-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Layer 1: install deps only (cached unless pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Layer 2: install the project itself (rebuilt only when src/ changes)
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ============================================================
# Stage 2 — runtime: minimal image with Java for SQLcl
# ============================================================
FROM python:3.13-slim AS runtime

# Java is required to run Oracle SQLcl in -mcp mode.
# curl is required for the HEALTHCHECK probe.
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user
RUN groupadd --system app \
    && useradd --system --gid app --home /workspace --shell /sbin/nologin app

WORKDIR /workspace

# Bring the resolved .venv from the builder stage
COPY --from=builder --chown=app:app /app/.venv /workspace/.venv

# Source + skill index. SQLcl is provided via the /workspace/sqlcl_files volume
# (bind-mount your local SQLcl install or pre-bake an image that copies it in).
COPY --chown=app:app src/     ./src/
COPY --chown=app:app skills/  ./skills/
COPY --chown=app:app scripts/ ./scripts/

# Persistence dirs for AsyncSqliteSaver / AsyncSqliteStore + SQLcl wallet/config.
RUN mkdir -p /workspace/memory /workspace/sqlcl_files \
    && chown -R app:app /workspace
VOLUME ["/workspace/memory", "/workspace/sqlcl_files"]

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/src \
    API_WORKERS=1 \
    SQLCL_PATH=/workspace/sqlcl_files/bin/sql

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:8000/health || exit 1

CMD ["sh", "-c", "fastapi run src/nl2sql_agent/main.py --host 0.0.0.0 --port 8000 --workers $API_WORKERS"]

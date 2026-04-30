# syntax=docker/dockerfile:1.7

# ============================================================
# Stage 1 — builder: resolve deps + build .venv with uv
# ============================================================
# NOTE: builder WORKDIR and UV_PROJECT_ENVIRONMENT must match the runtime
# WORKDIR + venv path. Entry-point scripts (e.g. .venv/bin/fastapi) bake in
# absolute shebangs like `#!/workspace/.venv/bin/python`, so if the venv lives
# at /app/.venv in the builder and gets COPYed to /workspace/.venv at runtime,
# every console script breaks with `sh: not found` (bad interpreter).
FROM python:3.13-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /workspace

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
# curl is required for the HEALTHCHECK probe and the install scripts.
# unzip is required by scripts/install-{sqlcl,instantclient}.sh.
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless \
        curl \
        unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user
RUN groupadd --system app \
    && useradd --system --gid app --home /workspace --shell /sbin/nologin app

WORKDIR /workspace

# Bring the resolved .venv from the builder stage. Path MUST match the
# builder's UV_PROJECT_ENVIRONMENT or console-script shebangs break.
COPY --from=builder --chown=app:app /workspace/.venv /workspace/.venv

# Source + skill index + install scripts. SQLcl and Oracle Instant Client are
# downloaded into the image during build (Linux x64 binaries) — the host's
# Windows binaries under ./vendor and ./third_party are unusable in this
# container, so we never bind-mount them.
COPY --chown=app:app src/     ./src/
COPY --chown=app:app skills/  ./skills/
COPY --chown=app:app scripts/ ./scripts/

# Install Linux Oracle Instant Client (thick-mode runtime) + Linux SQLcl.
# Both scripts are idempotent and download from download.oracle.com.
# Pin INSTANTCLIENT_VERSION here so ORACLE_CLIENT_LIB_DIR below stays in sync.
ARG INSTANTCLIENT_VERSION=23.6.0.24.10
ARG INSTANTCLIENT_SLUG=2360000
ARG INSTANTCLIENT_DIRNAME=instantclient_23_6
RUN bash /workspace/scripts/install-instantclient.sh \
        --version "$INSTANTCLIENT_VERSION" \
        --slug    "$INSTANTCLIENT_SLUG" \
 && bash /workspace/scripts/install-sqlcl.sh \
 && chown -R app:app /workspace/third_party /workspace/vendor

# Persistence dir for AsyncSqliteSaver / AsyncSqliteStore.
RUN mkdir -p /workspace/memory \
    && chown -R app:app /workspace/memory
VOLUME ["/workspace/memory"]

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/src \
    API_WORKERS=1 \
    SQLCL_PATH=/workspace/vendor/sqlcl/bin/sql \
    ORACLE_CLIENT_MODE=thick \
    ORACLE_CLIENT_LIB_DIR=/workspace/third_party/instantclient_23_6

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:8000/health || exit 1

CMD ["sh", "-c", "fastapi run src/nl2sql_agent/main.py --host 0.0.0.0 --port 8000 --workers $API_WORKERS"]

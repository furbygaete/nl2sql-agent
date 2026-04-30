FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV API_WORKERS=1

# Java is required to run Oracle SQLcl in -mcp mode.
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source + skill index. SQLcl is provided via the /workspace/sqlcl_files volume
# (bind-mount your local SQLcl install or pre-bake an image that copies it in).
COPY src/ ./src/
COPY skills/ ./skills/
COPY scripts/ ./scripts/

ENV PYTHONPATH=/workspace/src
ENV SQLCL_PATH=/workspace/sqlcl_files/bin/sql

# Persistence for AsyncSqliteSaver / AsyncSqliteStore + SQLcl wallet/config.
VOLUME ["/workspace/memory", "/workspace/sqlcl_files"]

CMD ["sh", "-c", "fastapi run src/nl2sql_agent/main.py --workers $API_WORKERS"]

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: this file lives at <root>/src/nl2sql_agent/settings.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str
    openai_model: str = "gpt-4o"

    db_backend: str = "oracle"

    # Either set ORACLE_DSN (Easy Connect or TNS alias), or set ORACLE_HOST + ORACLE_SERVICE_NAME
    # (optional ORACLE_PORT, default 1521). If ORACLE_DSN is non-empty it wins.
    oracle_dsn: str = ""
    oracle_host: str | None = None
    oracle_port: int = 1521
    oracle_service_name: str | None = None
    # Optional at load time so a Postgres- or MySQL-only deployment does not
    # need to invent dummy Oracle credentials. The model validator below still
    # requires them when DB_BACKEND=oracle.
    oracle_ro_user: str = ""
    oracle_ro_password: str = ""
    oracle_client_mode: str = "thick"
    oracle_client_lib_dir: Path | None = None
    oracle_client_config_dir: Path | None = None

    # PostgreSQL settings (used when DB_BACKEND=postgres).
    postgres_dsn: str = ""
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_database: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None

    # MySQL settings (used when DB_BACKEND=mysql).
    mysql_dsn: str = ""
    mysql_host: str | None = None
    mysql_port: int = 3306
    mysql_database: str | None = None
    mysql_user: str | None = None
    mysql_password: str | None = None

    schema_path: Path = PROJECT_ROOT / "data" / "schema.json"
    # Max characters for schema block sent to the LLM (retrieval trim).
    schema_prompt_char_budget: int = 20_000
    # When true, pick relevant tables from the question instead of sending the full catalog.
    schema_retrieval_max_tables: int = 12
    schema_retrieval_fuzzy_cutoff: float = 0.42
    # Used by tools.run_select_sql to retry once after a schema-mismatch error.
    sql_cure_validate_enabled: bool = True

    max_rows: int = 1000
    query_timeout_s: int = 30
    chat_rate_limit_enabled: bool = True
    chat_rate_limit_requests: int = 30
    chat_rate_limit_window_s: int = 60

    host: str = "127.0.0.1"
    port: int = 8000

    # --- LangGraph agent stack (oracle-sqlcl-chat port) ---
    # Anthropic is the alternate provider; OpenAI fields above stay primary.
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    # SQLcl in -mcp stdio mode. Empty SQLCL_PATH disables the MCP bridge,
    # which lets the legacy /ask path keep booting before Phase 3 lands.
    sqlcl_path: str = ""
    sqlcl_connections: str = ""
    # When set, SQLcl reads/writes its connection wallet inside this directory
    # (relative to the repo root) instead of the user's home dir. Set to e.g.
    # ".sqlcl" to keep all SQLcl state in the repo. Empty = use ~/.dbtools.
    sqlcl_user_dir: str = ""
    connection_store_path: Path = PROJECT_ROOT / "data" / "connections.json"

    @field_validator("schema_path", "connection_store_path", mode="after")
    @classmethod
    def _anchor_to_project_root(cls, value: Path) -> Path:
        # Resolve relative paths (e.g. from .env) against the repo root so the
        # same file is used regardless of the working directory the app is
        # launched from.
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    system_prompt: str = (
        "You are an expert assistant for natural-language to SQL. "
        "Use the available tools to introspect schema, generate read-only "
        "SELECT statements, and execute them via the guarded executor. "
        "Never modify data."
    )
    filesystem_prompt: str = (
        "Save relevant facts about the user (preferred tables, naming hints, "
        "past queries) into per-user memory so future sessions stay personalised."
    )

    nicegui_storage_secret: str = "change-me-in-production"
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""

    @model_validator(mode="after")
    def _validate_backend_configuration(self) -> Self:
        # Connection details are sourced primarily from data/connections.json
        # at chat time (selected via the GUI sidebar or the API's
        # `connection_id`). Env-backed fields are advisory defaults only, so
        # this validator now only enforces that DB_BACKEND is structurally
        # valid. Missing credentials surface as a clear error at the moment a
        # tool actually tries to open a connection.
        backend = (self.db_backend or "").strip().lower()
        if backend not in {"oracle", "postgres", "mysql"}:
            raise ValueError("DB_BACKEND must be one of: oracle, postgres, mysql.")
        return self

    def env_backend_is_configured(self) -> bool:
        """True when the env-backed defaults can produce a usable connection.

        Used by callers that fall back to env when no runtime profile is set.
        """
        backend = (self.db_backend or "").strip().lower()
        if backend == "oracle":
            user = (self.oracle_ro_user or "").strip()
            password = (self.oracle_ro_password or "").strip()
            if not (user and password):
                return False
            d = (self.oracle_dsn or "").strip()
            host = (self.oracle_host or "").strip()
            svc = (self.oracle_service_name or "").strip()
            return bool(d or (host and svc))
        if backend == "postgres":
            d = (self.postgres_dsn or "").strip()
            host = (self.postgres_host or "").strip()
            database = (self.postgres_database or "").strip()
            user = (self.postgres_user or "").strip()
            password = (self.postgres_password or "").strip()
            return bool(d or (host and database and user and password))
        # mysql
        d = (self.mysql_dsn or "").strip()
        host = (self.mysql_host or "").strip()
        database = (self.mysql_database or "").strip()
        user = (self.mysql_user or "").strip()
        password = (self.mysql_password or "").strip()
        return bool(d or (host and database and user and password))

    @property
    def sqlglot_dialect(self) -> str:
        backend = (self.db_backend or "").strip().lower()
        if backend == "postgres":
            return "postgres"
        if backend == "mysql":
            return "mysql"
        return "oracle"

    @property
    def resolved_oracle_dsn(self) -> str:
        d = (self.oracle_dsn or "").strip()
        if d:
            return d
        host = (self.oracle_host or "").strip()
        svc = (self.oracle_service_name or "").strip()
        return f"{host}:{self.oracle_port}/{svc}"

    @property
    def resolved_postgres_dsn(self) -> str:
        d = (self.postgres_dsn or "").strip()
        if d:
            return d
        host = (self.postgres_host or "").strip()
        database = (self.postgres_database or "").strip()
        user = (self.postgres_user or "").strip()
        password = (self.postgres_password or "").strip()
        return (
            f"host={host} port={self.postgres_port} dbname={database} "
            f"user={user} password={password}"
        )

    @property
    def mysql_connect_kwargs(self) -> dict[str, str | int]:
        d = (self.mysql_dsn or "").strip()
        if d:
            return {"dsn": d}
        return {
            "host": (self.mysql_host or "").strip(),
            "port": self.mysql_port,
            "database": (self.mysql_database or "").strip(),
            "user": (self.mysql_user or "").strip(),
            "password": (self.mysql_password or "").strip(),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

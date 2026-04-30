from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str
    openai_model: str = "gpt-4o"

    # Either set ORACLE_DSN (Easy Connect or TNS alias), or set ORACLE_HOST + ORACLE_SERVICE_NAME
    # (optional ORACLE_PORT, default 1521). If ORACLE_DSN is non-empty it wins.
    oracle_dsn: str = ""
    oracle_host: str | None = None
    oracle_port: int = 1521
    oracle_service_name: str | None = None
    oracle_ro_user: str
    oracle_ro_password: str
    oracle_client_mode: str = "thick"
    oracle_client_lib_dir: Path | None = None
    oracle_client_config_dir: Path | None = None

    schema_path: Path = Path("data/schema.json")
    # Max characters for schema block sent to the LLM (as_prompt / retrieval trim).
    schema_prompt_char_budget: int = 20_000
    # When true, pick relevant tables from the question instead of sending the full catalog.
    schema_retrieval_enabled: bool = True
    schema_retrieval_max_tables: int = 12
    schema_retrieval_fuzzy_cutoff: float = 0.42
    sql_cure_validate_enabled: bool = True
    sql_repair_enabled: bool = True
    # User-requested policy: only one safe retry after a recoverable DB failure.
    sql_repair_max_attempts: int = 1

    max_rows: int = 1000
    query_timeout_s: int = 30
    ask_rate_limit_enabled: bool = True
    ask_rate_limit_requests: int = 30
    ask_rate_limit_window_s: int = 60

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

    system_prompt: str = (
        "You are an expert assistant for natural-language to Oracle SQL. "
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
    def _oracle_connect_present(self) -> Self:
        d = (self.oracle_dsn or "").strip()
        host = (self.oracle_host or "").strip()
        svc = (self.oracle_service_name or "").strip()
        if d or (host and svc):
            return self
        raise ValueError(
            "Oracle connection: set ORACLE_DSN, or set ORACLE_HOST and ORACLE_SERVICE_NAME "
            "(optional ORACLE_PORT, default 1521)."
        )

    @property
    def resolved_oracle_dsn(self) -> str:
        d = (self.oracle_dsn or "").strip()
        if d:
            return d
        host = (self.oracle_host or "").strip()
        svc = (self.oracle_service_name or "").strip()
        return f"{host}:{self.oracle_port}/{svc}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

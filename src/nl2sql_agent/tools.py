"""LangChain @tool wrappers around the existing safety net.

Exposes three tools to the LangGraph agent so it can stay inside the guarded
read-only path even when SQLcl-MCP tools are also available:

- run_select_sql(sql)            — sqlglot validation + SELECT-only guard
- find_relevant_tables(question) — fuzzy table/FK-neighbour selection
- verify_identifier_in_catalog   — ALL_OBJECTS existence check

The tools read settings + schema lazily so import-time has no Oracle deps.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from functools import lru_cache
from typing import Any

from langchain_core.tools import tool
from loguru import logger

from .catalog import lookup_accessible_object_names
from .executor import (
    NonSelectSqlError,
    cure_sql_against_schema,
    run_select,
)
from .schema_loader import SchemaContext, load_schema
from .schema_retrieval import build_llm_schema_prompt
from .runtime_connection import get_runtime_connection
from .settings import Settings, get_settings


@lru_cache(maxsize=1)
def _schema_context() -> SchemaContext:
    settings = get_settings()
    return load_schema(
        settings.schema_path,
        prompt_char_budget=settings.schema_prompt_char_budget,
    )


def _settings() -> Settings:
    base = get_settings()
    profile = get_runtime_connection()
    if profile is None:
        return base
    return profile.apply_to_settings(base)


def _coerce_cell(value: Any) -> Any:
    """Make oracledb row cells JSON-serialisable for the agent."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value) if value % 1 else int(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return str(value)


@tool
async def run_select_sql(sql: str) -> dict[str, Any]:
    """Execute a read-only SQL SELECT and return columns + rows.

    The SQL is validated with sqlglot (active backend dialect) and refused if it
    contains any DML/DDL/PLSQL keywords. Rows are capped by MAX_ROWS and
    timed out by QUERY_TIMEOUT_S. On a recoverable schema mismatch the
    cure-and-validate step retries once against schema.json metadata.

    Args:
        sql: A single Oracle SELECT statement.

    Returns:
        dict with keys: columns (list[str]), rows (list[list]),
        row_count (int), elapsed_ms (int), cured_sql (str | None).
    """
    settings = _settings()
    cured: str | None = None
    try:
        result = run_select(sql, settings)
    except NonSelectSqlError:
        raise
    except Exception:
        if not settings.sql_cure_validate_enabled:
            raise
        try:
            cured = cure_sql_against_schema(
                sql, _schema_context(), dialect=settings.sqlglot_dialect
            )
        except Exception as cure_exc:
            logger.warning(f"cure_sql_against_schema failed: {cure_exc}")
            raise
        result = run_select(cured, settings)

    rows = [[_coerce_cell(c) for c in row] for row in result["rows"]]
    return {
        "columns": result["columns"],
        "rows": rows,
        "row_count": result["row_count"],
        "elapsed_ms": result["elapsed_ms"],
        "cured_sql": cured,
    }


@tool
async def find_relevant_tables(question: str, k: int = 8) -> dict[str, Any]:
    """Pick the most relevant tables from schema.json for a natural-language question.

    Uses fuzzy matching on table names + FK neighbour expansion + entity hints.
    Returns both the chosen table names and the rendered TABLE … (cols) prompt
    block so the agent can write SQL without a second round-trip.

    Args:
        question: The user's question in natural language.
        k: Maximum number of tables to return (defaults to 8).

    Returns:
        dict with keys: tables (list[str]), prompt_block (str).
    """
    ctx = _schema_context()
    settings = _settings()
    prompt_block, used = build_llm_schema_prompt(
        ctx,
        question,
        enabled=True,
        max_tables=max(1, min(k, settings.schema_retrieval_max_tables)),
        fuzzy_name_cutoff=settings.schema_retrieval_fuzzy_cutoff,
    )
    return {"tables": used, "prompt_block": prompt_block}


@tool
async def verify_identifier_in_catalog(name: str) -> dict[str, Any]:
    """Check whether a table/view name exists in the active backend catalog.

    Useful when the model is uncertain whether a candidate name is a real
    object the read-only user can see.

    Args:
        name: The object name to check (case-insensitive).

    Returns:
        dict with keys: name (str, uppercased), exists (bool).
    """
    settings = _settings()
    found = lookup_accessible_object_names([name], settings)
    upper = name.strip().upper()
    return {"name": upper, "exists": upper in found}


AGENT_TOOLS = [run_select_sql, find_relevant_tables, verify_identifier_in_catalog]

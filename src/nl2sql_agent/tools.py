"""LangChain @tool wrappers around the existing safety net.

Exposes read-only tools to the LangGraph agent so it can stay inside the guarded
read-only path even when SQLcl-MCP tools are also available:

- run_select_sql(sql)            — sqlglot validation + SELECT-only guard
- find_relevant_tables(question) — fuzzy table/FK-neighbour selection
- verify_identifier_in_catalog   — ALL_OBJECTS existence check
- get_package_source             — PACKAGE / PACKAGE BODY text from ALL_SOURCE
- get_function_source            — FUNCTION text from ALL_SOURCE
- get_procedure_source           — PROCEDURE text from ALL_SOURCE
- get_view_definition            — VIEW query text from ALL_VIEWS
- get_materialized_view_definition — MV query text from ALL_MVIEWS

The tools read settings + schema lazily so import-time has no Oracle deps.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

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

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


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


def _normalize_identifier(value: str, *, field_name: str) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(
            f"Invalid {field_name!r}. Use an unquoted Oracle identifier "
            "(letters, numbers, _, $, #)."
        )
    return normalized


def _owner_filter_sql(owner: str | None) -> str:
    if owner:
        owner_name = _normalize_identifier(owner, field_name="owner")
        return f"OWNER = '{owner_name}'"
    return "1=1"


def _format_source_lines(rows: list[list[Any]], *, max_lines: int) -> dict[str, Any]:
    total = len(rows)
    limited_rows = rows[:max_lines]
    source_lines = []
    for row in limited_rows:
        if len(row) < 4:
            continue
        source_lines.append(
            {
                "owner": row[0],
                "name": row[1],
                "type": row[2],
                "line": row[3],
                "text": row[4] if len(row) > 4 else "",
            }
        )
    text = "".join((line.get("text") or "") for line in source_lines)
    return {
        "source_lines": source_lines,
        "source_text": text,
        "line_count": total,
        "returned_lines": len(source_lines),
        "truncated": total > max_lines,
    }


def _run_catalog_select(sql: str) -> dict[str, Any]:
    settings = _settings()
    return run_select(sql, settings)


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


@tool
async def get_package_source(
    name: str,
    owner: str | None = None,
    max_lines: int = 1200,
) -> dict[str, Any]:
    """Fetch Oracle package source text from ALL_SOURCE.

    Args:
        name: Package name (unquoted Oracle identifier).
        owner: Optional owner/schema filter.
        max_lines: Maximum source lines to return.

    Returns:
        dict containing metadata plus `source_lines` and concatenated `source_text`.
    """
    package_name = _normalize_identifier(name, field_name="name")
    limit = max(1, min(int(max_lines), 5000))
    owner_filter = _owner_filter_sql(owner)
    sql = f"""
SELECT OWNER, NAME, TYPE, LINE, TEXT
  FROM ALL_SOURCE
 WHERE {owner_filter}
   AND NAME = '{package_name}'
   AND TYPE IN ('PACKAGE', 'PACKAGE BODY')
 ORDER BY OWNER, TYPE, LINE
"""
    result = _run_catalog_select(sql)
    payload = _format_source_lines(result["rows"], max_lines=limit)
    payload.update(
        {
            "name": package_name,
            "owner": _normalize_identifier(owner, field_name="owner") if owner else None,
            "object_types": ["PACKAGE", "PACKAGE BODY"],
        }
    )
    return payload


@tool
async def get_function_source(
    name: str,
    owner: str | None = None,
    max_lines: int = 1200,
) -> dict[str, Any]:
    """Fetch Oracle function source text from ALL_SOURCE."""
    function_name = _normalize_identifier(name, field_name="name")
    limit = max(1, min(int(max_lines), 5000))
    owner_filter = _owner_filter_sql(owner)
    sql = f"""
SELECT OWNER, NAME, TYPE, LINE, TEXT
  FROM ALL_SOURCE
 WHERE {owner_filter}
   AND NAME = '{function_name}'
   AND TYPE = 'FUNCTION'
 ORDER BY OWNER, LINE
"""
    result = _run_catalog_select(sql)
    payload = _format_source_lines(result["rows"], max_lines=limit)
    payload.update(
        {
            "name": function_name,
            "owner": _normalize_identifier(owner, field_name="owner") if owner else None,
            "object_types": ["FUNCTION"],
        }
    )
    return payload


@tool
async def get_procedure_source(
    name: str,
    owner: str | None = None,
    max_lines: int = 1200,
) -> dict[str, Any]:
    """Fetch Oracle procedure source text from ALL_SOURCE."""
    procedure_name = _normalize_identifier(name, field_name="name")
    limit = max(1, min(int(max_lines), 5000))
    owner_filter = _owner_filter_sql(owner)
    sql = f"""
SELECT OWNER, NAME, TYPE, LINE, TEXT
  FROM ALL_SOURCE
 WHERE {owner_filter}
   AND NAME = '{procedure_name}'
   AND TYPE = 'PROCEDURE'
 ORDER BY OWNER, LINE
"""
    result = _run_catalog_select(sql)
    payload = _format_source_lines(result["rows"], max_lines=limit)
    payload.update(
        {
            "name": procedure_name,
            "owner": _normalize_identifier(owner, field_name="owner") if owner else None,
            "object_types": ["PROCEDURE"],
        }
    )
    return payload


def _fetch_view_or_mview_definition(
    *,
    name: str,
    owner: str | None,
    object_type: Literal["VIEW", "MATERIALIZED VIEW"],
) -> dict[str, Any]:
    object_name = _normalize_identifier(name, field_name="name")
    owner_filter = _owner_filter_sql(owner)
    if object_type == "VIEW":
        sql = f"""
SELECT OWNER, VIEW_NAME AS NAME, TEXT AS QUERY_TEXT
  FROM ALL_VIEWS
 WHERE {owner_filter}
   AND VIEW_NAME = '{object_name}'
 ORDER BY OWNER
"""
    else:
        sql = f"""
SELECT OWNER, MVIEW_NAME AS NAME, QUERY AS QUERY_TEXT
  FROM ALL_MVIEWS
 WHERE {owner_filter}
   AND MVIEW_NAME = '{object_name}'
 ORDER BY OWNER
"""
    result = _run_catalog_select(sql)
    rows = result["rows"]
    definitions = []
    for row in rows:
        if len(row) < 3:
            continue
        definitions.append(
            {
                "owner": row[0],
                "name": row[1],
                "query_text": row[2] or "",
            }
        )
    return {
        "name": object_name,
        "owner": _normalize_identifier(owner, field_name="owner") if owner else None,
        "object_type": object_type,
        "definitions": definitions,
        "count": len(definitions),
    }


@tool
async def get_view_definition(name: str, owner: str | None = None) -> dict[str, Any]:
    """Fetch Oracle view query text from ALL_VIEWS."""
    return _fetch_view_or_mview_definition(name=name, owner=owner, object_type="VIEW")


@tool
async def get_materialized_view_definition(
    name: str, owner: str | None = None
) -> dict[str, Any]:
    """Fetch Oracle materialized-view query text from ALL_MVIEWS."""
    return _fetch_view_or_mview_definition(
        name=name,
        owner=owner,
        object_type="MATERIALIZED VIEW",
    )


AGENT_TOOLS = [
    run_select_sql,
    find_relevant_tables,
    verify_identifier_in_catalog,
    get_package_source,
    get_function_source,
    get_procedure_source,
    get_view_definition,
    get_materialized_view_definition,
]

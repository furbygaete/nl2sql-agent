import re
import time
from typing import Any

import oracledb
from sqlglot import exp, parse, parse_one

from nl2sql_agent.schema_loader import SchemaContext
from nl2sql_agent.settings import Settings


FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|BEGIN|CALL|EXEC|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

FORBIDDEN_EXPRESSION_KEYS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "merge",
        "create",
        "drop",
        "alter",
        "truncate",
        "command",
        "grant",
        "revoke",
        "transaction",
    }
)

ALLOWED_ROOT_EXPRESSION_KEYS = frozenset(
    {
        "select",
        "union",
        "intersect",
        "except",
    }
)


class NonSelectSqlError(ValueError):
    """Raised when SQL is not read-only."""


class SqlCureError(NonSelectSqlError):
    """Raised when SQL cannot be validated/cured against schema metadata."""


def validate_read_only_sql(sql: str) -> None:
    normalized = sql.strip()
    if not normalized:
        raise NonSelectSqlError("SQL cannot be empty")

    if FORBIDDEN_PATTERN.search(normalized):
        raise NonSelectSqlError("SQL contains forbidden write/ddl/procedural keywords")

    try:
        statements = parse(normalized, read="oracle")
    except Exception as exc:
        raise NonSelectSqlError(f"SQL parse failed for Oracle dialect: {exc}") from exc

    if len(statements) != 1:
        raise NonSelectSqlError("Only one SQL statement is allowed")

    root = statements[0]
    if root.key not in ALLOWED_ROOT_EXPRESSION_KEYS:
        raise NonSelectSqlError("Only read-only SELECT queries are allowed")

    for node in root.walk():
        if node.key in FORBIDDEN_EXPRESSION_KEYS:
            raise NonSelectSqlError("SQL contains non-read-only expressions")


def cure_sql_against_schema(sql: str, schema_ctx: SchemaContext) -> str:
    validate_read_only_sql(sql)

    try:
        parsed = parse_one(sql, read="oracle")
    except Exception as exc:  # pragma: no cover - exercised through main repair loop
        raise SqlCureError(f"SQL parse failed for Oracle dialect: {exc}") from exc

    known_objects = schema_ctx.known_object_names()
    table_columns = _table_columns_map(schema_ctx.raw_schema)
    alias_to_table: dict[str, str] = {}

    for table in parsed.find_all(exp.Table):
        current = (table.name or "").upper()
        if not current:
            continue

        corrected = _best_identifier(current, known_objects)
        if corrected is None:
            raise SqlCureError(f"Unknown table or view '{current}' in generated SQL")

        if corrected != current:
            table.set("this", exp.to_identifier(corrected))

        alias = (table.alias or "").upper()
        if alias:
            alias_to_table[alias] = corrected
        alias_to_table[corrected] = corrected

    for column in parsed.find_all(exp.Column):
        col_name = (column.name or "").upper()
        if not col_name:
            continue
        table_qualifier = (column.table or "").upper()

        if table_qualifier:
            resolved = alias_to_table.get(table_qualifier, table_qualifier)
            known_cols = table_columns.get(resolved)
            if not known_cols:
                # For views/synonyms without column metadata, keep as-is.
                continue
            if col_name in known_cols:
                continue
            fixed_col = _best_identifier(col_name, known_cols)
            if fixed_col is None:
                raise SqlCureError(
                    f"Unknown column '{col_name}' for table '{resolved}' in generated SQL"
                )
            column.set("this", exp.to_identifier(fixed_col))
            continue

        # Unqualified column: validate across known tables in the query.
        in_scope_tables = [
            t for t in alias_to_table.values() if t in table_columns and table_columns[t]
        ]
        candidate_tables = [t for t in in_scope_tables if col_name in table_columns[t]]
        if candidate_tables:
            continue

        all_scope_columns = {
            c for t in in_scope_tables for c in table_columns.get(t, set())
        }
        fixed_col = _best_identifier(col_name, all_scope_columns)
        if fixed_col is None:
            raise SqlCureError(f"Unknown column '{col_name}' in generated SQL")
        column.set("this", exp.to_identifier(fixed_col))

    cured = parsed.sql(dialect="oracle")
    validate_read_only_sql(cured)
    return cured


def _table_columns_map(raw_schema: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table in raw_schema.get("tables", []):
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name", "") or "").strip().upper()
        if not table_name:
            continue
        cols: set[str] = set()
        for col in table.get("columns", []) or []:
            if not isinstance(col, dict):
                continue
            col_name = str(col.get("name", "") or "").strip().upper()
            if col_name:
                cols.add(col_name)
        out[table_name] = cols
    return out


def _best_identifier(name: str, allowed: set[str], *, cutoff: float = 0.78) -> str | None:
    if name in allowed:
        return name
    if not allowed:
        return None
    # Standard-library fuzzy match keeps dependencies small and deterministic.
    import difflib

    matches = difflib.get_close_matches(name, sorted(allowed), n=1, cutoff=cutoff)
    if not matches:
        return None
    return matches[0]


def run_select(sql: str, settings: Settings) -> dict[str, Any]:
    validate_read_only_sql(sql)

    start = time.perf_counter()
    connection = oracledb.connect(
        user=settings.oracle_ro_user,
        password=settings.oracle_ro_password,
        dsn=settings.resolved_oracle_dsn,
    )
    try:
        with connection.cursor() as cursor:
            cursor.callTimeout = settings.query_timeout_s * 1000
            cursor.arraysize = 200
            cursor.execute(sql)
            rows = cursor.fetchmany(settings.max_rows)
            columns = [desc[0] for desc in cursor.description or []]
    finally:
        connection.close()

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": elapsed_ms,
    }

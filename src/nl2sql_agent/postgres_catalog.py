"""PostgreSQL catalog helpers (accessible objects for the configured user)."""

from __future__ import annotations

import psycopg

from nl2sql_agent.settings import Settings

_POSTGRES_OBJECT_SQL = """
SELECT UPPER(TRIM(table_name)) AS obj_name
  FROM information_schema.tables
 WHERE table_type IN ('BASE TABLE', 'VIEW')
   AND UPPER(TRIM(table_name)) = ANY(%(names)s)
"""


def lookup_postgres_object_names(names: list[str], settings: Settings) -> set[str]:
    if not names:
        return set()

    normalized = [n.strip().upper() for n in names if n and str(n).strip()]
    if not normalized:
        return set()

    unique = sorted(set(normalized))
    connection = psycopg.connect(settings.resolved_postgres_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SET statement_timeout = {settings.query_timeout_s * 1000}"
            )
            cursor.execute(_POSTGRES_OBJECT_SQL, {"names": unique})
            rows = cursor.fetchall()
    finally:
        connection.close()

    return {str(r[0]).upper() for r in rows if r and r[0] is not None}

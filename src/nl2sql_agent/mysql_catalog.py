"""MySQL catalog helpers (accessible objects for the configured user)."""

from __future__ import annotations

import mysql.connector

from nl2sql_agent.settings import Settings

_MYSQL_OBJECT_SQL = """
SELECT UPPER(TRIM(table_name)) AS obj_name
  FROM information_schema.tables
 WHERE table_schema = %s
   AND table_type IN ('BASE TABLE', 'VIEW')
   AND UPPER(TRIM(table_name)) IN ({placeholders})
"""


def lookup_mysql_object_names(names: list[str], settings: Settings) -> set[str]:
    if not names:
        return set()

    normalized = [n.strip().upper() for n in names if n and str(n).strip()]
    if not normalized:
        return set()

    unique = sorted(set(normalized))
    placeholders = ", ".join(["%s"] * len(unique))
    sql = _MYSQL_OBJECT_SQL.format(placeholders=placeholders)
    params = [(settings.mysql_database or "").strip(), *unique]

    kwargs = settings.mysql_connect_kwargs.copy()
    dsn = kwargs.pop("dsn", "")
    if dsn:
        raise ValueError(
            "MYSQL_DSN is not supported by mysql-connector-python in this build. "
            "Use MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD."
        )

    connection = mysql.connector.connect(**kwargs)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SET SESSION max_execution_time = {settings.query_timeout_s * 1000}"
            )
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        connection.close()

    return {str(r[0]).upper() for r in rows if r and r[0] is not None}

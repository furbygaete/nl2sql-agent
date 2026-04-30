"""Oracle data-dictionary helpers (accessible objects for the RO user).

Used by the agent's `verify_identifier_in_catalog` tool to confirm that a
candidate table/view/MV name is actually visible to the read-only user
before the model writes SQL against it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import oracledb

if TYPE_CHECKING:
    from nl2sql_agent.settings import Settings

# Oracle catalogs: ALL_OBJECTS lists tables/views/MVs visible to the session.
# (There is no ALL_USER_OBJECTS view; USER_OBJECTS is owner-only.)
_ALL_OBJECT_SQL = """
SELECT UPPER(TRIM(OBJECT_NAME)) AS OBJ_NAME
  FROM ALL_OBJECTS
 WHERE OBJECT_TYPE IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')
   AND UPPER(TRIM(OBJECT_NAME)) IN ({placeholders})
"""


def lookup_accessible_object_names(names: list[str], settings: Settings) -> set[str]:
    """
    Return the subset of ``names`` (compared case-insensitively) that appear in
    ``ALL_OBJECTS`` as TABLE, VIEW, or MATERIALIZED VIEW for the current user.
    """
    if not names:
        return set()

    normalized = [n.strip().upper() for n in names if n and str(n).strip()]
    if not normalized:
        return set()

    unique: list[str] = []
    seen: set[str] = set()
    for n in normalized:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    placeholders = ", ".join(f":n{i}" for i in range(len(unique)))
    sql = _ALL_OBJECT_SQL.format(placeholders=placeholders)
    binds = {f"n{i}": unique[i] for i in range(len(unique))}

    connection = oracledb.connect(
        user=settings.oracle_ro_user,
        password=settings.oracle_ro_password,
        dsn=settings.resolved_oracle_dsn,
    )
    try:
        with connection.cursor() as cursor:
            cursor.callTimeout = settings.query_timeout_s * 1000
            cursor.execute(sql, binds)
            rows = cursor.fetchall()
    finally:
        connection.close()

    return {str(r[0]).upper() for r in rows if r and r[0] is not None}

"""Oracle data-dictionary helpers (accessible objects for the RO user)."""

from __future__ import annotations

import difflib
import re
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


_SQL_RESERVED = frozenset(
    """
    SELECT FROM WHERE AND OR NOT NULL LIKE IN BETWEEN JOIN LEFT RIGHT INNER OUTER
    ON AS BY GROUP ORDER HAVING LIMIT FETCH FIRST ROWS ONLY WITH CASE WHEN THEN
    ELSE END DISTINCT COUNT SUM AVG MIN MAX EXISTS UNION ALL INTERSECT MINUS
    FOR UPDATE OF ASC DESC IS TRUE FALSE UNKNOWN OVER PARTITION ROW_NUMBER RANK
    DENSE_RANK QUALIFY CAST SYSDATE CURRENT_DATE CURRENT_TIMESTAMP TRUNC TO_CHAR
    TO_DATE NVL COALESCE DECODE CONNECT LEVEL START PRIOR REGEXP_LIKE SUBSTR
    INSTR LENGTH UPPER LOWER TRIM LTRIM RTRIM REPLACE TRANSLATE ROUND FLOOR CEIL
    ABS MOD POWER GREATEST LEAST LISTAGG WITHIN EXTRACT YEAR MONTH DAY HOUR
    MINUTE SECOND ADD_MONTHS MONTHS_BETWEEN NEXT_DAY LAST_DAY
    """.split()
)


def _question_identifier_tokens(question: str) -> set[str]:
    # Match Oracle-style identifiers and ordinary words (same idea as schema_retrieval).
    found = re.findall(r"\b[A-Za-z][A-Za-z0-9_]{1,}\b", question)
    return {t.upper() for t in found}


def unknown_schema_tokens(question: str, known_names: set[str]) -> list[str]:
    """
    Tokens from the question that are not listed in ``schema.json`` (tables,
    views, synonyms) and are not obvious SQL keywords.
    """
    explicit_refs = {
        m.group(1).upper()
        for m in re.finditer(
            r"\b(?:from|join|table|view|into|update|delete\s+from|merge\s+into)\s+([A-Za-z][A-Za-z0-9_]*)\b",
            question,
            flags=re.IGNORECASE,
        )
    }

    out: list[str] = []
    seen: set[str] = set()
    for raw_tok in re.findall(r"\b[A-Za-z][A-Za-z0-9_]{1,}\b", question):
        tok = raw_tok.upper()
        if tok in known_names or tok in _SQL_RESERVED:
            continue
        if len(tok) < 3:
            continue
        looks_like_identifier = (
            tok in explicit_refs
            or raw_tok.isupper()
            or "_" in raw_tok
            or any(ch.isdigit() for ch in raw_tok)
        )
        if not looks_like_identifier:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return sorted(out)


def friendly_missing_source_message(missing_tokens: list[str]) -> str:
    base = "I couldn't find the source table for your question."
    if not missing_tokens:
        return base
    if len(missing_tokens) == 1:
        return f"{base} Nothing in the database matched \"{missing_tokens[0]}\"."
    listed = ", ".join(f'"{t}"' for t in missing_tokens[:5])
    suffix = " …" if len(missing_tokens) > 5 else ""
    return f"{base} Nothing in the database matched: {listed}{suffix}"


def verify_question_objects_against_catalog(
    question: str,
    known_names: set[str],
    settings: Settings,
) -> str | None:
    """
    If the question mentions identifiers that are not in ``schema.json``, check
    ``ALL_OBJECTS``. When none of those names exist in the catalog, return a
    user-facing message; otherwise return ``None`` so the pipeline can continue.
    """
    candidates = unknown_schema_tokens(question, known_names)
    if not candidates:
        return None
    try:
        found = lookup_accessible_object_names(candidates, settings)
    except oracledb.Error:
        # Catalog lookup is best-effort; do not block NL2SQL if privileges/network fail.
        return None

    # If candidates are close to known schema object names, let retrieval/LLM proceed.
    # This avoids false 404s for slight singular/plural or spelling variations.
    if not found and _has_similar_known_name(
        candidates,
        known_names,
        cutoff=max(0.72, settings.schema_retrieval_fuzzy_cutoff),
    ):
        return None

    if not found:
        return friendly_missing_source_message(candidates)
    return None


def _has_similar_known_name(
    candidates: list[str],
    known_names: set[str],
    *,
    cutoff: float,
) -> bool:
    if not candidates or not known_names:
        return False
    normalized_known = {
        _normalized_name(n): n for n in known_names if _normalized_name(n)
    }
    keys = list(normalized_known.keys())
    if not keys:
        return False

    for candidate in candidates:
        norm_candidate = _normalized_name(candidate)
        if not norm_candidate:
            continue
        if difflib.get_close_matches(norm_candidate, keys, n=1, cutoff=cutoff):
            return True
    return False


def _normalized_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", name.upper(), flags=re.ASCII)
    if cleaned.endswith("ES") and len(cleaned) >= 6:
        return cleaned[:-2]
    if cleaned.endswith("S") and len(cleaned) >= 5:
        return cleaned[:-1]
    return cleaned

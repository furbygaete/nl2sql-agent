"""Backend-aware catalog helpers."""

from __future__ import annotations

from nl2sql_agent.mysql_catalog import lookup_mysql_object_names
from nl2sql_agent.oracle_catalog import lookup_accessible_object_names as lookup_oracle_object_names
from nl2sql_agent.postgres_catalog import lookup_postgres_object_names
from nl2sql_agent.settings import Settings


def lookup_accessible_object_names(names: list[str], settings: Settings) -> set[str]:
    backend = settings.db_backend.strip().lower()
    if backend == "postgres":
        return lookup_postgres_object_names(names, settings)
    if backend == "mysql":
        return lookup_mysql_object_names(names, settings)
    return lookup_oracle_object_names(names, settings)

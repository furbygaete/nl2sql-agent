from nl2sql_agent import catalog
from nl2sql_agent.settings import Settings


def _base_settings(**kwargs):
    base = {
        "openai_api_key": "x",
        "oracle_dsn": "db:1521/xe",
        "oracle_ro_user": "ro",
        "oracle_ro_password": "pw",
    }
    base.update(kwargs)
    return Settings(**base)


def test_catalog_router_postgres(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "lookup_postgres_object_names",
        lambda names, settings: {"ORDERS"},
    )
    settings = _base_settings(
        db_backend="postgres",
        postgres_host="localhost",
        postgres_database="db",
        postgres_user="u",
        postgres_password="p",
    )
    assert catalog.lookup_accessible_object_names(["orders"], settings) == {"ORDERS"}


def test_catalog_router_mysql(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "lookup_mysql_object_names",
        lambda names, settings: {"ORDERS"},
    )
    settings = _base_settings(
        db_backend="mysql",
        mysql_host="localhost",
        mysql_database="db",
        mysql_user="u",
        mysql_password="p",
    )
    assert catalog.lookup_accessible_object_names(["orders"], settings) == {"ORDERS"}

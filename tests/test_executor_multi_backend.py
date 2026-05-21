from nl2sql_agent import executor
from nl2sql_agent.executor import cure_sql_against_schema, validate_read_only_sql
from nl2sql_agent.schema_loader import SchemaContext
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


def test_validate_read_only_sql_uses_requested_dialect():
    validate_read_only_sql("select now()::timestamp", dialect="postgres")


def test_cure_sql_against_schema_respects_dialect():
    ctx = SchemaContext(
        raw_schema={
            "tables": [{"name": "ORDERS", "columns": [{"name": "ID", "data_type": "INT"}]}]
        },
        prompt_char_budget=4000,
    )
    cured = cure_sql_against_schema('select "id" from "orders"', ctx, dialect="postgres")
    assert "FROM" in cured.upper()


def test_run_select_routes_to_postgres(monkeypatch):
    called = {}

    def fake(sql, settings):
        called["backend"] = settings.db_backend
        return {"columns": [], "rows": [], "row_count": 0, "elapsed_ms": 1}

    monkeypatch.setattr(executor, "_run_select_postgres", fake)

    settings = _base_settings(
        db_backend="postgres",
        postgres_host="localhost",
        postgres_database="db",
        postgres_user="u",
        postgres_password="p",
    )
    executor.run_select("select 1", settings)
    assert called["backend"] == "postgres"


def test_run_select_routes_to_mysql(monkeypatch):
    called = {}

    def fake(sql, settings):
        called["backend"] = settings.db_backend
        return {"columns": [], "rows": [], "row_count": 0, "elapsed_ms": 1}

    monkeypatch.setattr(executor, "_run_select_mysql", fake)

    settings = _base_settings(
        db_backend="mysql",
        mysql_host="localhost",
        mysql_database="db",
        mysql_user="u",
        mysql_password="p",
    )
    executor.run_select("select 1", settings)
    assert called["backend"] == "mysql"

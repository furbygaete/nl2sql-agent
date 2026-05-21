import pytest

from nl2sql_agent.settings import Settings


def test_resolved_oracle_dsn_from_host_and_service():
    s = Settings(
        openai_api_key="x",
        oracle_dsn="",
        oracle_host="db.example.com",
        oracle_port=1522,
        oracle_service_name="ORCLPDB1",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    assert s.resolved_oracle_dsn == "db.example.com:1522/ORCLPDB1"


def test_resolved_oracle_dsn_prefers_oracle_dsn():
    s = Settings(
        openai_api_key="x",
        oracle_dsn="other:1521/XE",
        oracle_host="ignored",
        oracle_service_name="IGNORED",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    assert s.resolved_oracle_dsn == "other:1521/XE"


def test_invalid_backend_value_is_rejected():
    with pytest.raises(ValueError, match="DB_BACKEND must be one of"):
        Settings(openai_api_key="x", db_backend="sqlite")


def test_env_backend_is_configured_oracle_incomplete():
    s = Settings(
        openai_api_key="x",
        oracle_dsn="",
        oracle_host="",
        oracle_service_name="",
        oracle_ro_user="",
        oracle_ro_password="",
    )
    assert s.env_backend_is_configured() is False


def test_env_backend_is_configured_postgres_incomplete():
    s = Settings(
        openai_api_key="x",
        db_backend="postgres",
        postgres_dsn="",
        postgres_host="",
        postgres_database="",
        postgres_user="",
        postgres_password="",
    )
    assert s.env_backend_is_configured() is False


def test_env_backend_is_configured_mysql_incomplete():
    s = Settings(
        openai_api_key="x",
        db_backend="mysql",
        mysql_dsn="",
        mysql_host="",
        mysql_database="",
        mysql_user="",
        mysql_password="",
    )
    assert s.env_backend_is_configured() is False


def test_env_backend_is_configured_oracle_complete():
    s = Settings(
        openai_api_key="x",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    assert s.env_backend_is_configured() is True


def test_resolved_postgres_dsn_from_fields():
    s = Settings(
        openai_api_key="x",
        db_backend="postgres",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
        postgres_host="pg.example.com",
        postgres_port=5433,
        postgres_database="analytics",
        postgres_user="reader",
        postgres_password="secret",
    )
    assert s.resolved_postgres_dsn == (
        "host=pg.example.com port=5433 dbname=analytics user=reader password=secret"
    )


def test_sqlglot_dialect_follows_backend():
    oracle = Settings(
        openai_api_key="x",
        db_backend="oracle",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    postgres = Settings(
        openai_api_key="x",
        db_backend="postgres",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
        postgres_host="localhost",
        postgres_database="db",
        postgres_user="u",
        postgres_password="p",
    )
    mysql = Settings(
        openai_api_key="x",
        db_backend="mysql",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
        mysql_host="localhost",
        mysql_database="db",
        mysql_user="u",
        mysql_password="p",
    )

    assert oracle.sqlglot_dialect == "oracle"
    assert postgres.sqlglot_dialect == "postgres"
    assert mysql.sqlglot_dialect == "mysql"


def test_default_toggles():
    s = Settings(
        openai_api_key="x",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    assert s.sql_cure_validate_enabled is True
    assert s.chat_rate_limit_enabled is True
    assert s.chat_rate_limit_requests == 30
    assert s.chat_rate_limit_window_s == 60

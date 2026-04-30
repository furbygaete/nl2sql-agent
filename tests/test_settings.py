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


def test_oracle_requires_dsn_or_host_and_service():
    with pytest.raises(ValueError, match="Oracle connection"):
        Settings(
            openai_api_key="x",
            oracle_dsn="",
            oracle_host="",
            oracle_service_name="",
            oracle_ro_user="ro",
            oracle_ro_password="pw",
        )


def test_sql_repair_defaults():
    s = Settings(
        openai_api_key="x",
        oracle_dsn="db:1521/xe",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    assert s.sql_cure_validate_enabled is True
    assert s.sql_repair_enabled is True
    assert s.sql_repair_max_attempts == 1

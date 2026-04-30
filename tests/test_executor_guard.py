import pytest

from nl2sql_agent.executor import (
    NonSelectSqlError,
    SqlCureError,
    classify_oracle_error,
    cure_sql_against_schema,
    is_safe_retry_class,
    validate_read_only_sql,
)
from nl2sql_agent.schema_loader import SchemaContext


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM employees",
        "WITH cte AS (SELECT 1 AS x FROM dual) SELECT x FROM cte",
        "select employee_id from employees fetch first 5 rows only",
    ],
)
def test_validate_read_only_sql_accepts_select_and_with(sql: str):
    validate_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE employees SET salary = 1",
        "INSERT INTO employees (employee_id) VALUES (1)",
        "DELETE FROM employees",
        "DROP TABLE employees",
        "ALTER TABLE employees ADD test_col NUMBER",
        "BEGIN dbms_output.put_line('x'); END;",
        "SELECT * FROM employees; DELETE FROM employees",
        "EXPLAIN PLAN FOR SELECT * FROM employees",
        "SELECT * FROM employees FOR UPDATE",
    ],
)
def test_validate_read_only_sql_rejects_non_read_only(sql: str):
    with pytest.raises(NonSelectSqlError):
        validate_read_only_sql(sql)


def _schema_ctx() -> SchemaContext:
    return SchemaContext(
        raw_schema={
            "tables": [
                {
                    "name": "EMPLOYEES",
                    "columns": [
                        {"name": "EMPLOYEE_ID"},
                        {"name": "FIRST_NAME"},
                    ],
                }
            ]
        }
    )


def test_cure_sql_against_schema_fixes_simple_typos():
    sql = "select employeeid, first_nam from employes"
    cured = cure_sql_against_schema(sql, _schema_ctx())
    assert "FROM EMPLOYEES" in cured
    assert "EMPLOYEE_ID" in cured
    assert "FIRST_NAME" in cured


def test_cure_sql_against_schema_rejects_unknown_table():
    with pytest.raises(SqlCureError, match="Unknown table"):
        cure_sql_against_schema("select * from departments", _schema_ctx())


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ORA-00904: invalid identifier", "missing_column"),
        ("ORA-00942: table or view does not exist", "missing_table"),
        ("ORA-00918: column ambiguously defined", "ambiguous_column"),
        ("ORA-00933: SQL command not properly ended", "syntax"),
        ("ORA-01031: insufficient privileges", "permission"),
        ("ORA-12170: TNS connect timeout occurred", "timeout"),
        ("ORA-20000: custom error", "other"),
    ],
)
def test_classify_oracle_error_by_message(message: str, expected: str):
    assert classify_oracle_error(Exception(message)) == expected


def test_is_safe_retry_class_allows_only_recoverable_groups():
    assert is_safe_retry_class("syntax")
    assert is_safe_retry_class("missing_table")
    assert is_safe_retry_class("missing_column")
    assert is_safe_retry_class("ambiguous_column")
    assert not is_safe_retry_class("permission")

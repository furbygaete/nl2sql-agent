import pytest

from nl2sql_agent.executor import (
    NonSelectSqlError,
    SqlCureError,
    cure_sql_against_schema,
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

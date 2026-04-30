import json

import pytest

from nl2sql_agent.schema_loader import DEFAULT_PROMPT_CHAR_BUDGET, load_schema


def test_load_schema_and_prompt_format(tmp_path):
    schema = {
        "tables": [
            {
                "name": "EMPLOYEES",
                "columns": [
                    {"name": "EMPLOYEE_ID", "data_type": "NUMBER"},
                    {"name": "DEPARTMENT_ID", "data_type": "NUMBER"},
                ],
                "foreign_keys": [
                    {
                        "column_name": "DEPARTMENT_ID",
                        "referenced_table": "DEPARTMENTS",
                        "referenced_column": "DEPARTMENT_ID",
                    }
                ],
            }
        ],
        "views": [{"name": "V_EMPLOYEES"}],
        "synonyms": [{"name": "EMP", "table_owner": "HR", "table_name": "EMPLOYEES"}],
    }
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")

    ctx = load_schema(path)
    prompt = ctx.as_prompt()

    assert "TABLE EMPLOYEES" in prompt
    assert "EMPLOYEE_ID NUMBER" in prompt
    assert "DEPARTMENT_ID NUMBER FK->DEPARTMENTS.DEPARTMENT_ID" in prompt
    assert "VIEWS V_EMPLOYEES" in prompt
    assert "SYNONYMS EMP->HR.EMPLOYEES" in prompt


def test_load_schema_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_schema(tmp_path / "missing.json")


def test_load_schema_accepts_utf16_file(tmp_path):
    schema = {
        "tables": [
            {
                "name": "EMPLOYEES",
                "columns": [{"name": "EMPLOYEE_ID", "data_type": "NUMBER"}],
                "foreign_keys": [],
            }
        ]
    }
    path = tmp_path / "schema_utf16.json"
    path.write_text(json.dumps(schema), encoding="utf-16")

    ctx = load_schema(path)
    prompt = ctx.as_prompt()

    assert "TABLE EMPLOYEES" in prompt
    assert "EMPLOYEE_ID NUMBER" in prompt


def test_load_schema_accepts_utf16le_without_bom(tmp_path):
    schema = {
        "tables": [
            {
                "name": "EMPLOYEES",
                "columns": [{"name": "EMPLOYEE_ID", "data_type": "NUMBER"}],
                "foreign_keys": [],
            }
        ]
    }
    path = tmp_path / "schema_utf16le_no_bom.json"
    path.write_bytes(json.dumps(schema).encode("utf-16-le"))

    ctx = load_schema(path)
    prompt = ctx.as_prompt()

    assert "TABLE EMPLOYEES" in prompt
    assert "EMPLOYEE_ID NUMBER" in prompt


def test_prompt_is_truncated_when_over_budget(tmp_path):
    schema = {
        "tables": [
            {
                "name": "BIG_TABLE",
                "columns": [
                    {"name": f"COL_{index}", "data_type": "VARCHAR2"}
                    for index in range(1500)
                ],
                "foreign_keys": [],
            }
        ]
    }
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")

    ctx = load_schema(path)
    prompt = ctx.as_prompt()

    assert len(prompt) <= DEFAULT_PROMPT_CHAR_BUDGET
    assert prompt.endswith("...")


def test_load_schema_invalid_json_raises_value_error(tmp_path):
    path = tmp_path / "schema_invalid.json"
    path.write_text("SQLcl: Release 25.2 Production", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        load_schema(path)


def test_load_schema_recovers_wrapped_json_lines(tmp_path):
    # Simulates SQLcl hard wraps that split JSON tokens across lines.
    wrapped_json = (
        '{"tables":[{"name":"EMPLOYEES","columns":[{"name":"EMPLOYEE'
        '\n'
        '_ID","data_type":"NUMBER"}],"foreign_keys":[]}]}'
    )
    path = tmp_path / "schema_wrapped.json"
    path.write_text(wrapped_json, encoding="utf-8")

    ctx = load_schema(path)
    prompt = ctx.as_prompt()

    assert "TABLE EMPLOYEES" in prompt
    assert "EMPLOYEE_ID NUMBER" in prompt


def test_known_object_names_includes_tables_views_synonyms(tmp_path):
    schema = {
        "tables": [{"name": "EMPLOYEES", "columns": [], "foreign_keys": []}],
        "views": [{"name": "V_EMP"}],
        "synonyms": [{"name": "EMP", "table_owner": "HR", "table_name": "EMPLOYEES"}],
    }
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    ctx = load_schema(path)
    names = ctx.known_object_names()
    assert names == {"EMPLOYEES", "V_EMP", "EMP"}


def test_load_schema_recovers_banner_prefixed_json(tmp_path):
    schema = {
        "tables": [
            {
                "name": "EMPLOYEES",
                "columns": [{"name": "EMPLOYEE_ID", "data_type": "NUMBER"}],
                "foreign_keys": [],
            }
        ]
    }
    content = (
        "Picked up JAVA_TOOL_OPTIONS: --enable-native-access=ALL-UNNAMED\r\n"
        + json.dumps(schema)
    )
    path = tmp_path / "schema_banner_prefixed.json"
    path.write_text(content, encoding="utf-8")

    ctx = load_schema(path)
    prompt = ctx.as_prompt()

    assert "TABLE EMPLOYEES" in prompt
    assert "EMPLOYEE_ID NUMBER" in prompt

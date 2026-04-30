from types import SimpleNamespace

from nl2sql_agent.llm import SqlGenerator
from nl2sql_agent.schema_loader import SchemaContext
from nl2sql_agent.settings import Settings


class FakeResponsesClient:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


def _make_settings(**kwargs) -> Settings:
    base = dict(
        openai_api_key="x",
        oracle_dsn="dsn",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )
    base.update(kwargs)
    return Settings(**base)


def test_generate_sql_strips_fence_and_builds_prompt():
    settings = _make_settings()
    generator = SqlGenerator(settings)
    fake = FakeResponsesClient("```sql\nSELECT * FROM employees\n```")
    generator._client = SimpleNamespace(responses=fake)  # type: ignore[attr-defined]

    ctx = SchemaContext(raw_schema={"tables": [{"name": "EMPLOYEES", "columns": []}]})
    sql, tables_meta = generator.generate_sql("List employees", ctx)

    assert sql == "SELECT * FROM employees"
    assert fake.calls
    payload = fake.calls[0]
    assert payload["model"] == settings.openai_model
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["role"] == "user"
    assert "List employees" in payload["input"][1]["content"]
    assert "TABLE EMPLOYEES" in payload["input"][1]["content"]
    assert tables_meta is not None
    assert "EMPLOYEES" in tables_meta


def test_generate_sql_full_schema_when_retrieval_disabled():
    settings = _make_settings(schema_retrieval_enabled=False)
    generator = SqlGenerator(settings)
    fake = FakeResponsesClient("SELECT 1 FROM dual")
    generator._client = SimpleNamespace(responses=fake)  # type: ignore[attr-defined]

    ctx = SchemaContext(
        raw_schema={
            "tables": [
                {"name": "A", "columns": []},
                {"name": "B", "columns": []},
            ]
        }
    )
    sql, tables_meta = generator.generate_sql("anything", ctx)

    assert sql == "SELECT 1 FROM dual"
    assert tables_meta is None
    user = fake.calls[0]["input"][1]["content"]
    assert "TABLE A" in user and "TABLE B" in user


def test_repair_sql_uses_repair_prompt_and_returns_sql():
    settings = _make_settings()
    generator = SqlGenerator(settings)
    fake = FakeResponsesClient("```sql\nSELECT employee_id FROM employees\n```")
    generator._client = SimpleNamespace(responses=fake)  # type: ignore[attr-defined]
    ctx = SchemaContext(raw_schema={"tables": [{"name": "EMPLOYEES", "columns": []}]})

    repaired = generator.repair_sql(
        question="list employee ids",
        previous_sql="select employeeid from employes",
        issue="missing_table: ORA-00942",
        ctx=ctx,
    )

    assert repaired == "SELECT employee_id FROM employees"
    call = fake.calls[0]
    assert call["input"][0]["role"] == "system"
    assert "repair Oracle SQL".lower() in call["input"][0]["content"].lower()
    assert "missing_table: ORA-00942" in call["input"][1]["content"]

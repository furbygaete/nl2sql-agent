from nl2sql_agent.schema_loader import SchemaContext
from nl2sql_agent.schema_retrieval import build_llm_schema_prompt


def test_build_llm_schema_prompt_disabled_returns_full_and_empty_names():
    ctx = SchemaContext(
        raw_schema={"tables": [{"name": "X", "columns": [{"name": "ID", "data_type": "NUMBER"}]}]},
        prompt_char_budget=10_000,
    )
    text, names = build_llm_schema_prompt(
        ctx, "hello", enabled=False, max_tables=5, fuzzy_name_cutoff=0.42
    )
    assert names == []
    assert "TABLE X" in text


def test_build_llm_schema_prompt_fallback_first_tables_when_no_match():
    ctx = SchemaContext(
        raw_schema={
            "tables": [
                {"name": "ZZZ", "columns": []},
                {"name": "AAA", "columns": []},
            ]
        },
        prompt_char_budget=10_000,
    )
    text, names = build_llm_schema_prompt(
        ctx, "@@@###$$$", enabled=True, max_tables=2, fuzzy_name_cutoff=0.99
    )
    assert "TABLE AAA" in text
    assert "TABLE ZZZ" in text
    assert set(names) == {"AAA", "ZZZ"}


def test_build_llm_schema_prompt_uses_counting_entity_hint():
    ctx = SchemaContext(
        raw_schema={
            "tables": [
                {"name": "ORDERS", "columns": [{"name": "ID", "data_type": "NUMBER"}]},
                {"name": "CLIENTS", "columns": [{"name": "ID", "data_type": "NUMBER"}]},
            ]
        },
        prompt_char_budget=10_000,
    )
    _, names = build_llm_schema_prompt(
        ctx,
        "how many clients there are?",
        enabled=True,
        max_tables=1,
        fuzzy_name_cutoff=0.42,
    )
    assert names == ["CLIENTS"]

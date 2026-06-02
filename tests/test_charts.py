from nl2sql_agent.charts import (
    generate_chart_image_payload,
    parse_tabular_tool_result,
)


def test_parse_tabular_tool_result_accepts_json_dict_payload():
    raw = '{"columns":["MONTH","TOTAL"],"rows":[["2026-01",10],["2026-02",12]]}'
    parsed = parse_tabular_tool_result(raw)
    assert parsed is not None
    columns, rows = parsed
    assert columns == ["MONTH", "TOTAL"]
    assert rows[0] == ["2026-01", 10]


def test_generate_chart_image_payload_emits_png_payload_for_numeric_series():
    payload = generate_chart_image_payload(
        ["MONTH", "TOTAL"],
        [["2026-01", 10], ["2026-02", 12], ["2026-03", 15]],
    )
    assert payload is not None
    assert payload["mime"] == "image/png"
    assert isinstance(payload["data"], str)
    assert len(payload["data"]) > 100
    assert payload["spec"]["y"] == "TOTAL"

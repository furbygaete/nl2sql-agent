from nl2sql_agent.generator import _wants_chart_output


def test_chart_output_requires_explicit_request():
    assert _wants_chart_output("show me a chart of row counts") is True
    assert _wants_chart_output("plot this result as a graph") is True


def test_chart_output_not_enabled_for_generic_query():
    assert _wants_chart_output("list top 10 tables by row count") is False

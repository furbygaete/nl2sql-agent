import asyncio

import pytest

from nl2sql_agent import tools


def test_normalize_identifier_accepts_oracle_identifier():
    assert tools._normalize_identifier("pkg_orders", field_name="name") == "PKG_ORDERS"


def test_normalize_identifier_rejects_invalid_characters():
    with pytest.raises(ValueError):
        tools._normalize_identifier("pkg-orders", field_name="name")


def test_fetch_view_definition_uses_expected_catalog(monkeypatch):
    def fake_run(sql: str):
        assert "FROM ALL_VIEWS" in sql
        return {
            "rows": [
                ["APP", "VW_ORDERS", "SELECT * FROM ORDERS"],
            ]
        }

    monkeypatch.setattr(tools, "_run_catalog_select", fake_run)
    result = tools._fetch_view_or_mview_definition(
        name="vw_orders",
        owner="app",
        object_type="VIEW",
    )
    assert result["count"] == 1
    assert result["definitions"][0]["owner"] == "APP"
    assert "ORDERS" in result["definitions"][0]["query_text"]


def test_fetch_mview_definition_uses_expected_catalog(monkeypatch):
    def fake_run(sql: str):
        assert "FROM ALL_MVIEWS" in sql
        return {
            "rows": [
                ["APP", "MV_ORDERS", "SELECT * FROM ORDERS"],
            ]
        }

    monkeypatch.setattr(tools, "_run_catalog_select", fake_run)
    result = tools._fetch_view_or_mview_definition(
        name="mv_orders",
        owner="app",
        object_type="MATERIALIZED VIEW",
    )
    assert result["count"] == 1
    assert result["definitions"][0]["name"] == "MV_ORDERS"


def test_get_package_source_limits_lines(monkeypatch):
    rows = []
    for i in range(1, 6):
        rows.append(["APP", "PKG_TEST", "PACKAGE BODY", i, f"line {i}\n"])

    monkeypatch.setattr(tools, "_run_catalog_select", lambda _sql: {"rows": rows})
    payload = asyncio.run(
        tools.get_package_source.ainvoke(
            {"name": "pkg_test", "owner": "app", "max_lines": 3}
        )
    )

    assert payload["line_count"] == 5
    assert payload["returned_lines"] == 3
    assert payload["truncated"] is True
    assert payload["source_text"] == "line 1\nline 2\nline 3\n"

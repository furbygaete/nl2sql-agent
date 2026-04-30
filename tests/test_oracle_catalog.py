"""Unit tests for Oracle catalog helpers (mocked DB)."""

from unittest.mock import MagicMock

import pytest

from nl2sql_agent import oracle_catalog
from nl2sql_agent.oracle_catalog import lookup_accessible_object_names
from nl2sql_agent.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="x",
        oracle_dsn="localhost:1521/XE",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )


def test_lookup_returns_empty_for_empty_input(settings):
    assert lookup_accessible_object_names([], settings) == set()
    assert lookup_accessible_object_names(["", "  "], settings) == set()


def test_lookup_normalizes_and_dedups(monkeypatch, settings):
    captured: dict = {}

    def fake_connect(**kwargs):
        cursor = MagicMock()
        cursor.fetchall.return_value = [("EMPLOYEES",)]
        cursor_ctx = MagicMock()
        cursor_ctx.__enter__.return_value = cursor
        cursor_ctx.__exit__.return_value = False

        def execute(sql, binds):
            captured["sql"] = sql
            captured["binds"] = binds
        cursor.execute.side_effect = execute

        connection = MagicMock()
        connection.cursor.return_value = cursor_ctx
        return connection

    monkeypatch.setattr(oracle_catalog.oracledb, "connect", fake_connect)

    result = lookup_accessible_object_names(
        ["employees", "EMPLOYEES", " departments "],
        settings,
    )
    assert result == {"EMPLOYEES"}
    # Deduplication happens before binding.
    assert set(captured["binds"].values()) == {"EMPLOYEES", "DEPARTMENTS"}

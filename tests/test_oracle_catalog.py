"""Unit tests for Oracle catalog verification (mocked DB)."""

import pytest

from nl2sql_agent import oracle_catalog
from nl2sql_agent.oracle_catalog import (
    friendly_missing_source_message,
    unknown_schema_tokens,
    verify_question_objects_against_catalog,
)
from nl2sql_agent.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="x",
        oracle_dsn="localhost:1521/XE",
        oracle_ro_user="ro",
        oracle_ro_password="pw",
    )


def test_unknown_schema_tokens_excludes_known_and_reserved():
    known = {"EMPLOYEES", "DEPARTMENTS"}
    q = "SELECT count from EMPLOYEES join DEPARTMENTS on weird_table X"
    tokens = unknown_schema_tokens(q, known)
    assert "WEIRD_TABLE" in tokens
    assert "EMPLOYEES" not in tokens
    assert "DEPARTMENTS" not in tokens
    assert "SELECT" not in tokens
    assert "COUNT" not in tokens


def test_friendly_missing_source_message_single_and_multi():
    m1 = friendly_missing_source_message(["FOO"])
    assert "I couldn't find the source table" in m1
    assert "FOO" in m1
    m2 = friendly_missing_source_message(["A", "B", "C", "D", "E", "F"])
    assert "A" in m2 and "E" in m2
    assert "…" in m2


def test_verify_returns_none_when_no_off_schema_candidates(settings):
    assert (
        verify_question_objects_against_catalog(
            "how many rows in EMPLOYEES",
            {"EMPLOYEES"},
            settings,
        )
        is None
    )


def test_verify_returns_message_when_catalog_has_no_match(monkeypatch, settings):
    monkeypatch.setattr(oracle_catalog, "lookup_accessible_object_names", lambda names, s: set())

    msg = verify_question_objects_against_catalog(
        "show me all rows from MYMYTHICALTABLE please",
        {"EMPLOYEES"},
        settings,
    )
    assert msg is not None
    assert "I couldn't find the source table" in msg
    assert "MYMYTHICALTABLE" in msg


def test_verify_returns_none_when_catalog_finds_off_schema_name(monkeypatch, settings):
    def fake_lookup(names, s):
        return set(names)

    monkeypatch.setattr(oracle_catalog, "lookup_accessible_object_names", fake_lookup)

    assert (
        verify_question_objects_against_catalog(
            "query ZZZ for totals",
            {"EMPLOYEES"},
            settings,
        )
        is None
    )


def test_verify_returns_none_when_catalog_finds_at_least_one_candidate(monkeypatch, settings):
    monkeypatch.setattr(
        oracle_catalog,
        "lookup_accessible_object_names",
        lambda names, s: {"REAL_TABLE"} & set(names),
    )

    assert (
        verify_question_objects_against_catalog(
            "show REAL_TABLE with UNKNOWN_BUSINESS_TERM",
            {"EMPLOYEES"},
            settings,
        )
        is None
    )


def test_verify_ignores_plain_natural_language_terms(monkeypatch, settings):
    monkeypatch.setattr(oracle_catalog, "lookup_accessible_object_names", lambda names, s: set())

    assert (
        verify_question_objects_against_catalog(
            "how many clients there are?",
            {"EMPLOYEES", "CUSTOMERS"},
            settings,
        )
        is None
    )


def test_verify_uses_similarity_for_close_table_name(monkeypatch, settings):
    monkeypatch.setattr(oracle_catalog, "lookup_accessible_object_names", lambda names, s: set())

    assert (
        verify_question_objects_against_catalog(
            "select * from CLIENTS",
            {"CLIENT", "ORDERS"},
            settings,
        )
        is None
    )


def test_verify_returns_none_on_oracledb_error(monkeypatch, settings):
    import oracledb

    def boom(names, s):
        raise oracledb.DatabaseError("network")

    monkeypatch.setattr(oracle_catalog, "lookup_accessible_object_names", boom)

    assert (
        verify_question_objects_against_catalog(
            "from NOT_IN_SCHEMA at all",
            set(),
            settings,
        )
        is None
    )

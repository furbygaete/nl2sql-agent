"""Per-request active connection profile context."""

from __future__ import annotations

from contextvars import ContextVar, Token

from nl2sql_agent.connection_store import DbConnectionProfile


_ACTIVE_PROFILE: ContextVar[DbConnectionProfile | None] = ContextVar(
    "active_connection_profile",
    default=None,
)


def set_runtime_connection(profile: DbConnectionProfile | None) -> Token:
    return _ACTIVE_PROFILE.set(profile)


def reset_runtime_connection(token: Token) -> None:
    _ACTIVE_PROFILE.reset(token)


def get_runtime_connection() -> DbConnectionProfile | None:
    return _ACTIVE_PROFILE.get()

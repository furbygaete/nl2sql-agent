"""File-backed connection profiles for runtime database selection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from nl2sql_agent.mcp_bridge import parse_connection_string
from nl2sql_agent.settings import Settings


class DbConnectionProfile(BaseModel):
    id: str
    name: str
    db_type: Literal["oracle", "postgres"]

    oracle_dsn: str = ""
    oracle_host: str = ""
    oracle_port: int = 1521
    oracle_service_name: str = ""
    oracle_user: str = ""
    oracle_password: str = ""

    postgres_dsn: str = ""
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_database: str = ""
    postgres_user: str = ""
    postgres_password: str = ""

    @model_validator(mode="after")
    def _validate_profile(self) -> "DbConnectionProfile":
        if not self.id.strip():
            raise ValueError("Connection id is required.")
        if not self.name.strip():
            raise ValueError("Connection name is required.")

        if self.db_type == "oracle":
            dsn = self.oracle_dsn.strip()
            if dsn:
                if not self.oracle_user.strip() or not self.oracle_password.strip():
                    raise ValueError("Oracle user/password are required.")
                return self
            if (
                self.oracle_host.strip()
                and self.oracle_service_name.strip()
                and self.oracle_user.strip()
                and self.oracle_password.strip()
            ):
                return self
            raise ValueError(
                "Oracle profile requires ORACLE_DSN + user/password, or "
                "ORACLE_HOST + ORACLE_SERVICE_NAME + user/password."
            )

        dsn = self.postgres_dsn.strip()
        if dsn:
            return self
        if (
            self.postgres_host.strip()
            and self.postgres_database.strip()
            and self.postgres_user.strip()
            and self.postgres_password.strip()
        ):
            return self
        raise ValueError(
            "Postgres profile requires POSTGRES_DSN, or POSTGRES_HOST + "
            "POSTGRES_DATABASE + POSTGRES_USER + POSTGRES_PASSWORD."
        )

    def oracle_target(self) -> str:
        if self.oracle_dsn.strip():
            return self.oracle_dsn.strip()
        return f"{self.oracle_host.strip()}:{self.oracle_port}/{self.oracle_service_name.strip()}"

    def to_sqlcl_connection_string(self) -> str | None:
        if self.db_type != "oracle":
            return None
        return (
            f"{self.oracle_user.strip()}/"
            f"{self.oracle_password.strip()}@"
            f"{self.oracle_target()}"
        )

    def apply_to_settings(self, settings: Settings) -> Settings:
        if self.db_type == "oracle":
            return settings.model_copy(
                update={
                    "db_backend": "oracle",
                    "oracle_dsn": self.oracle_dsn.strip(),
                    "oracle_host": self.oracle_host.strip() or None,
                    "oracle_port": self.oracle_port,
                    "oracle_service_name": self.oracle_service_name.strip() or None,
                    "oracle_ro_user": self.oracle_user.strip(),
                    "oracle_ro_password": self.oracle_password.strip(),
                }
            )
        return settings.model_copy(
            update={
                "db_backend": "postgres",
                "postgres_dsn": self.postgres_dsn.strip(),
                "postgres_host": self.postgres_host.strip() or None,
                "postgres_port": self.postgres_port,
                "postgres_database": self.postgres_database.strip() or None,
                "postgres_user": self.postgres_user.strip() or None,
                "postgres_password": self.postgres_password.strip() or None,
            }
        )

    def target_display(self) -> str:
        if self.db_type == "oracle":
            return self.oracle_target()
        if self.postgres_dsn.strip():
            return self.postgres_dsn.strip()
        return f"{self.postgres_host.strip()}:{self.postgres_port}/{self.postgres_database.strip()}"

    def as_public(self, *, active_id: str | None) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "db_type": self.db_type,
            "target": self.target_display(),
            "is_active": self.id == active_id,
        }


class ConnectionStoreDocument(BaseModel):
    default_connection_id: str | None = None
    profiles: list[DbConnectionProfile] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_default(self) -> "ConnectionStoreDocument":
        if self.default_connection_id and not any(
            p.id == self.default_connection_id for p in self.profiles
        ):
            self.default_connection_id = None
        return self

    def get(self, connection_id: str | None) -> DbConnectionProfile | None:
        if not connection_id:
            return None
        for profile in self.profiles:
            if profile.id == connection_id:
                return profile
        return None

    def public_profiles(self, *, active_id: str | None) -> list[dict]:
        return [p.as_public(active_id=active_id) for p in self.profiles]

    def sqlcl_connections(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for p in self.profiles:
            if p.db_type != "oracle":
                continue
            conn_string = p.to_sqlcl_connection_string()
            if not conn_string:
                continue
            out.append({"nombre": p.id, "cadena": conn_string})
        return out


class FileConnectionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> ConnectionStoreDocument:
        if not self.path.exists():
            return ConnectionStoreDocument()
        try:
            raw = self.path.read_text(encoding="utf-8")
        except Exception:
            return ConnectionStoreDocument()
        if not raw.strip():
            return ConnectionStoreDocument()
        return ConnectionStoreDocument.model_validate_json(raw)

    def save(self, document: ConnectionStoreDocument) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = document.model_dump(mode="json")
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def upsert(
        self,
        profile: DbConnectionProfile,
        *,
        set_default: bool = False,
    ) -> ConnectionStoreDocument:
        document = self.load()
        replaced = False
        new_profiles: list[DbConnectionProfile] = []
        for existing in document.profiles:
            if existing.id == profile.id:
                new_profiles.append(profile)
                replaced = True
            else:
                new_profiles.append(existing)
        if not replaced:
            new_profiles.append(profile)
        document.profiles = new_profiles
        if set_default or not document.default_connection_id:
            document.default_connection_id = profile.id
        self.save(document)
        return self.load()

    def delete(self, connection_id: str) -> ConnectionStoreDocument:
        document = self.load()
        document.profiles = [p for p in document.profiles if p.id != connection_id]
        if document.default_connection_id == connection_id:
            document.default_connection_id = document.profiles[0].id if document.profiles else None
        self.save(document)
        return self.load()


def seed_profiles_from_settings(
    document: ConnectionStoreDocument,
    settings: Settings,
) -> ConnectionStoreDocument:
    """Seed file store from current env-backed settings when empty."""
    if document.profiles:
        return document

    seeded: list[DbConnectionProfile] = []

    oracle_profile = DbConnectionProfile(
        id="oracle-default",
        name="Oracle default",
        db_type="oracle",
        oracle_dsn=(settings.oracle_dsn or "").strip(),
        oracle_host=(settings.oracle_host or "").strip(),
        oracle_port=settings.oracle_port,
        oracle_service_name=(settings.oracle_service_name or "").strip(),
        oracle_user=settings.oracle_ro_user,
        oracle_password=settings.oracle_ro_password,
    )
    seeded.append(oracle_profile)

    postgres_ready = bool(
        (settings.postgres_dsn or "").strip()
        or (
            (settings.postgres_host or "").strip()
            and (settings.postgres_database or "").strip()
            and (settings.postgres_user or "").strip()
            and (settings.postgres_password or "").strip()
        )
    )
    if postgres_ready:
        seeded.append(
            DbConnectionProfile(
                id="postgres-default",
                name="Postgres default",
                db_type="postgres",
                postgres_dsn=(settings.postgres_dsn or "").strip(),
                postgres_host=(settings.postgres_host or "").strip(),
                postgres_port=settings.postgres_port,
                postgres_database=(settings.postgres_database or "").strip(),
                postgres_user=(settings.postgres_user or "").strip(),
                postgres_password=(settings.postgres_password or "").strip(),
            )
        )

    default_id = None
    if settings.db_backend.strip().lower() == "postgres" and postgres_ready:
        default_id = "postgres-default"
    elif seeded:
        default_id = seeded[0].id

    return ConnectionStoreDocument(default_connection_id=default_id, profiles=seeded)


def merge_profiles_from_env(
    document: ConnectionStoreDocument,
    settings: Settings,
) -> ConnectionStoreDocument:
    """Merge connection profiles from `.env` values into the file document.

    This keeps the JSON store as the source of truth while importing legacy
    env-defined connections (notably SQLCL_CONNECTIONS) that are not yet in it.
    Existing profile IDs are never overwritten by this merge.
    """
    merged = document.model_copy(deep=True)
    by_id: dict[str, DbConnectionProfile] = {p.id: p for p in merged.profiles}

    def add_if_missing(profile: DbConnectionProfile) -> None:
        if profile.id in by_id:
            return
        by_id[profile.id] = profile

    # Import SQLCL_CONNECTIONS Oracle entries: [name,user/pass@host:port/service]
    raw_sqlcl = (settings.sqlcl_connections or "").strip()
    if raw_sqlcl:
        for conn in parse_connection_string(raw_sqlcl):
            profile = _profile_from_sqlcl_entry(conn.get("nombre", ""), conn.get("cadena", ""))
            if profile:
                add_if_missing(profile)

    # Ensure the current env-backed Oracle/Postgres defaults are represented.
    oracle_ready = bool(
        (settings.oracle_dsn or "").strip()
        or (
            (settings.oracle_host or "").strip()
            and (settings.oracle_service_name or "").strip()
            and (settings.oracle_ro_user or "").strip()
            and (settings.oracle_ro_password or "").strip()
        )
    )
    if oracle_ready:
        add_if_missing(
            DbConnectionProfile(
                id="oracle-default",
                name="Oracle default",
                db_type="oracle",
                oracle_dsn=(settings.oracle_dsn or "").strip(),
                oracle_host=(settings.oracle_host or "").strip(),
                oracle_port=settings.oracle_port,
                oracle_service_name=(settings.oracle_service_name or "").strip(),
                oracle_user=(settings.oracle_ro_user or "").strip(),
                oracle_password=(settings.oracle_ro_password or "").strip(),
            )
        )

    postgres_ready = bool(
        (settings.postgres_dsn or "").strip()
        or (
            (settings.postgres_host or "").strip()
            and (settings.postgres_database or "").strip()
            and (settings.postgres_user or "").strip()
            and (settings.postgres_password or "").strip()
        )
    )
    if postgres_ready:
        add_if_missing(
            DbConnectionProfile(
                id="postgres-default",
                name="Postgres default",
                db_type="postgres",
                postgres_dsn=(settings.postgres_dsn or "").strip(),
                postgres_host=(settings.postgres_host or "").strip(),
                postgres_port=settings.postgres_port,
                postgres_database=(settings.postgres_database or "").strip(),
                postgres_user=(settings.postgres_user or "").strip(),
                postgres_password=(settings.postgres_password or "").strip(),
            )
        )

    merged.profiles = list(by_id.values())
    if not merged.default_connection_id and merged.profiles:
        preferred = "postgres-default" if (settings.db_backend or "").strip().lower() == "postgres" else "oracle-default"
        merged.default_connection_id = preferred if preferred in by_id else merged.profiles[0].id
    return merged


def _profile_from_sqlcl_entry(name: str, cadena: str) -> DbConnectionProfile | None:
    connection_name = (name or "").strip()
    payload = (cadena or "").strip()
    if not connection_name or not payload:
        return None
    # Canonical form: user/password@host:port/service
    match = re.match(r"^(?P<user>[^/]+)/(?P<password>[^@]+)@(?P<dsn>.+)$", payload)
    if not match:
        return None
    user = match.group("user").strip()
    password = match.group("password").strip()
    dsn = match.group("dsn").strip()
    if not user or not password or not dsn:
        return None
    return DbConnectionProfile(
        id=connection_name,
        name=connection_name,
        db_type="oracle",
        oracle_dsn=dsn,
        oracle_user=user,
        oracle_password=password,
    )

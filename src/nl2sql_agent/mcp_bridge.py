"""SQLcl MCP bridge.

Ports `parse_connection_string`, `sqlcl_init_config`, and `check_for_sqlcl`
from oracle-sqlcl-chat/app/config.py with two adjustments for nl2sql-agent:

1. Functions take an explicit `sqlcl_path` arg instead of reading a module-global,
   to keep coupling with `Settings` in one place (`main.py` lifespan).
2. `check_for_sqlcl` is a passive existence check. The source auto-downloads
   SQLcl from oracle.com when missing — that's appropriate inside a freshly
   provisioned container, but surprising on a developer workstation. The
   Dockerfile (Phase 8) is the right place to bundle SQLcl; this function
   raises if it cannot find the binary.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import TypedDict

from loguru import logger


class SqlclConnection(TypedDict):
    nombre: str
    cadena: str


def parse_connection_string(cadena_bruta: str) -> list[SqlclConnection]:
    bloques = re.findall(r"\[(.*?)\]", cadena_bruta)
    lista: list[SqlclConnection] = []
    for bloque in bloques:
        partes = bloque.split(",", 1)
        if len(partes) == 2:
            lista.append(
                SqlclConnection(nombre=partes[0].strip(), cadena=partes[1].strip())
            )
    return lista


def _build_subprocess_env(sqlcl_user_dir: str | None) -> dict[str, str]:
    """Build the env dict for SQLcl subprocesses.

    When `sqlcl_user_dir` is non-empty, point SQLcl at that directory by
    overriding `user.home` via JAVA_TOOL_OPTIONS. SQLcl reads `~/.dbtools/`
    relative to whatever Java thinks `user.home` is, so this redirects the
    connection wallet into the repo without touching the developer's actual
    home directory.
    """
    env = dict(os.environ)
    if sqlcl_user_dir:
        abs_dir = os.path.abspath(sqlcl_user_dir)
        os.makedirs(abs_dir, exist_ok=True)
        existing = env.get("JAVA_TOOL_OPTIONS", "")
        env["JAVA_TOOL_OPTIONS"] = (
            f"{existing} -Duser.home={abs_dir}".strip()
        )
        # Some SQLcl builds also honour SQLCL_USER_DIR directly.
        env["SQLCL_USER_DIR"] = abs_dir
    return env


def sqlcl_init_config(
    sqlcl_path: str,
    nombre_conexion: str,
    cadena_conexion: str,
    sqlcl_user_dir: str | None = None,
) -> None:
    """Persist a named SQLcl connection so the MCP server can `conn -name`.

    Uses the canonical `conn -save NAME -savepwd USER/PASS@DSN` syntax. The
    earlier `-sv` flag in the upstream port is not a standard SQLcl option
    and can cause the save to be ignored on some builds.

    `sqlcl_user_dir`, when set, redirects SQLcl's wallet into the given
    directory (typically inside the repo) so connections are kept project-
    local and don't leak into ~/.dbtools.
    """
    try:
        proc = subprocess.Popen(
            [sqlcl_path, "/NOLOG"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_build_subprocess_env(sqlcl_user_dir),
        )
        # Two commands: save the connection, then exit cleanly. `-savepwd`
        # makes the saved connection usable from a fresh subprocess (the MCP
        # session) without a password prompt.
        script = (
            f"conn -save {nombre_conexion} -savepwd {cadena_conexion}\nexit\n"
        )
        stdout, stderr = proc.communicate(input=script, timeout=30)

        # SQLcl is chatty; we always log both streams so failures are
        # debuggable. The saved-OK signal varies across SQLcl versions, so
        # we check several phrases.
        ok_signals = ("Connection saved", "Connected.", "Disconnected from")
        saved = any(sig in stdout for sig in ok_signals)

        if saved:
            logger.success(
                f"Conexión SQLcl guardada: {nombre_conexion} "
                f"(rc={proc.returncode})"
            )
        else:
            logger.error(
                f"No se pudo guardar la conexión '{nombre_conexion}' "
                f"(rc={proc.returncode}). Revise stdout/stderr abajo."
            )

        if stdout.strip():
            logger.info(f"[sqlcl stdout · {nombre_conexion}]\n{stdout.strip()}")
        if stderr.strip():
            logger.warning(f"[sqlcl stderr · {nombre_conexion}]\n{stderr.strip()}")
    except Exception:
        logger.exception(f"Error al ejecutar SQLcl ({sqlcl_path})")
        raise


def check_for_sqlcl(sqlcl_path: str) -> None:
    """Verify the SQLcl binary exists. Raises FileNotFoundError otherwise.

    Bundling SQLcl is a deployment concern (see Dockerfile / README), not a
    runtime auto-install. If you genuinely need auto-download, use the
    upstream oracle-sqlcl-chat helper or a build-time install step.
    """
    if not sqlcl_path:
        raise FileNotFoundError(
            "SQLCL_PATH is empty. Install Oracle SQLcl and set SQLCL_PATH "
            "to the absolute path of the `sql` (or `sql.exe`) launcher."
        )
    if not os.path.exists(sqlcl_path):
        raise FileNotFoundError(
            f"SQLcl binary not found at SQLCL_PATH={sqlcl_path!r}. "
            "Install SQLcl or correct the path."
        )
    logger.info(f"SQLcl detectado en {sqlcl_path}")

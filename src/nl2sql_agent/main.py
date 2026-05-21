from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger

from nl2sql_agent.generator import stream_agent_response
from nl2sql_agent.mcp_bridge import (
    check_for_sqlcl,
    sqlcl_init_config,
)
from nl2sql_agent.connection_store import (
    ConnectionStoreDocument,
    FileConnectionStore,
    merge_profiles_from_env,
    seed_profiles_from_settings,
)
from nl2sql_agent.models import UserMessage
from nl2sql_agent.runtime_connection import (
    get_runtime_connection,
    reset_runtime_connection,
    set_runtime_connection,
)
from nl2sql_agent.settings import Settings, get_settings


class SlidingWindowRateLimiter:
    """Simple in-memory per-key sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> int | None:
        """Returns retry-after seconds when the key is over limit, else None."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self._max_requests:
                retry_after = max(1, int(self._window_seconds - (now - bucket[0])) + 1)
                return retry_after

            bucket.append(now)
        return None


def configure_oracle_client(settings: Settings) -> None:
    if settings.db_backend.strip().lower() != "oracle":
        return
    mode = settings.oracle_client_mode.strip().lower()
    if mode != "thick":
        return

    import oracledb

    kwargs: dict[str, str] = {}
    if settings.oracle_client_lib_dir:
        kwargs["lib_dir"] = str(settings.oracle_client_lib_dir)
    if settings.oracle_client_config_dir:
        kwargs["config_dir"] = str(settings.oracle_client_config_dir)

    oracledb.init_oracle_client(**kwargs)


def _connect_tool_kwargs(connect_tool, connection_name: str) -> dict:
    """Build the kwargs dict for the SQLcl-MCP connect tool by inspecting its schema.

    Different SQLcl builds expose the connect tool with different field names
    ("connection_name", "name", "connection"). We pick the first string field
    that looks like one of those, then fall back to a single-field schema.
    """
    schema = getattr(connect_tool, "args_schema", None)
    fields: dict = {}
    if schema is not None:
        fields = getattr(schema, "model_fields", None) or {}

    candidates = [
        f for f in fields if any(k in f.lower() for k in ("name", "connection"))
    ]
    if candidates:
        return {candidates[0]: connection_name}

    if len(fields) == 1:
        return {next(iter(fields)): connection_name}

    # Last-resort guess; if this fails the warning path logs a clear error.
    return {"connection_name": connection_name}


async def _build_langgraph_agent(
    app: FastAPI,
    stack: AsyncExitStack,
    settings: Settings,
    connection_doc: ConnectionStoreDocument,
):
    """Build the LangGraph agent inside the lifespan AsyncExitStack.

    Returns ``(agent, parsed_connections, primary_connection_name)`` so the
    lifespan can stash connection metadata on ``app.state`` for the GUI and
    HTTP endpoints to surface. Raises on any setup failure so the caller
    can downgrade to "agent disabled" mode without crashing the app.
    """
    # Imports kept inside the function so importing main.py does not pull
    # langgraph + nicegui + mcp on every test run.
    from deepagents.backends import StoreBackend
    from deepagents.middleware import FilesystemMiddleware
    from langchain.agents import create_agent
    from langchain.agents.middleware import (
        ClearToolUsesEdit,
        ContextEditingMiddleware,
        SummarizationMiddleware,
        wrap_tool_call,
    )
    from langchain.messages import ToolMessage
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite import AsyncSqliteStore

    from nl2sql_agent.llm_factory import build_chat_model
    from nl2sql_agent.skills import SkillMiddleware
    from nl2sql_agent.tools import AGENT_TOOLS

    @wrap_tool_call
    async def handle_tool_errors(request, handler):
        try:
            return await handler(request)
        except Exception as exc:
            return ToolMessage(
                content=f"Tool error: Please check your input and try again. ({exc})",
                tool_call_id=request.tool_call["id"],
            )

    @wrap_tool_call
    async def track_active_connection(request, handler):
        """Mirror the agent's MCP `connect` calls onto app.state.

        The GUI sidebar reads ``app.state.active_connection`` on a timer so
        the green dot follows whichever saved connection the agent has
        actually opened, not just the boot-time primary.
        """
        result = await handler(request)
        tool_call = getattr(request, "tool_call", {}) or {}
        name = tool_call.get("name", "")
        if name in ("connect", "sqlcl-connect"):
            args = tool_call.get("args", {}) or {}
            for value in args.values():
                if isinstance(value, str) and value.strip():
                    new_active = value.strip()
                    if getattr(app.state, "active_connection", None) != new_active:
                        app.state.active_connection = new_active
                        logger.info(
                            f"SQLcl MCP active connection now '{new_active}' (via tool call)."
                        )
                    break
        return result

    mcp_tool_names: set[str] = set()

    os.makedirs("memory", exist_ok=True)

    checkpointer = await stack.enter_async_context(
        AsyncSqliteSaver.from_conn_string("./memory/checkpoints.sqlite")
    )
    await checkpointer.setup()

    store = await stack.enter_async_context(
        AsyncSqliteStore.from_conn_string("./memory/store.sqlite")
    )
    await store.setup()

    primary_connection: str | None = None
    parsed_conns: list[dict[str, str]] = []
    mcp_tools = []
    connect_tool = None
    if settings.db_backend.strip().lower() == "oracle" and settings.sqlcl_path:
        parsed_conns = connection_doc.sqlcl_connections()
        for conn in parsed_conns:
            sqlcl_init_config(
                settings.sqlcl_path,
                conn["nombre"],
                conn["cadena"],
                sqlcl_user_dir=settings.sqlcl_user_dir or None,
            )

        # Build the env for the long-running MCP subprocess so it reads the same
        # connection wallet that we just wrote into.
        mcp_env: dict[str, str] = {}
        if settings.sqlcl_user_dir:
            abs_dir = os.path.abspath(settings.sqlcl_user_dir)
            os.makedirs(abs_dir, exist_ok=True)
            mcp_env = {
                "JAVA_TOOL_OPTIONS": f"-Duser.home={abs_dir}",
                "SQLCL_USER_DIR": abs_dir,
            }
            logger.info(f"SQLcl wallet pinned to {abs_dir} (project-local).")

        mcp_client = MultiServerMCPClient(
            {
                "sqlcl": {
                    "command": settings.sqlcl_path,
                    "args": ["-mcp"],
                    "transport": "stdio",
                    **({"env": mcp_env} if mcp_env else {}),
                }
            }
        )
        mcp_session = await stack.enter_async_context(mcp_client.session("sqlcl"))
        mcp_tools = await load_mcp_tools(mcp_session)
        mcp_tool_names = {t.name for t in mcp_tools}
        logger.info(f"Herramientas MCP cargadas desde sqlcl: {[t.name for t in mcp_tools]}")

        # Probe what the MCP subprocess actually sees. If `sqlcl_init_config`
        # silently failed, the saved-connection list will be empty here and the
        # auto-connect will fail. Logging the result makes the failure mode
        # diagnose-by-eyeball.
        list_tool = next((t for t in mcp_tools if t.name == "list-connections"), None)
        if list_tool is not None:
            try:
                saved = await list_tool.ainvoke({})
                logger.info(f"SQLcl MCP saved connections (live probe): {saved}")
            except Exception as exc:
                logger.warning(f"list-connections probe failed: {exc}")

        # Auto-connect the SQLcl-MCP session to the first saved connection so the
        # agent does not have to guess which connection to open. The exact kwarg
        # name on the connect tool varies by MCP implementation, so we introspect
        # the args schema and pick the first string-typed field.
        connect_tool = next(
            (t for t in mcp_tools if t.name in {"connect", "sqlcl-connect"}),
            None,
        )
        if connect_tool is not None and parsed_conns:
            oracle_ids = {c["nombre"] for c in parsed_conns}
            default_id = (connection_doc.default_connection_id or "").strip()
            if default_id in oracle_ids:
                primary_connection = default_id
            else:
                primary_connection = parsed_conns[0]["nombre"]
            try:
                kwargs = _connect_tool_kwargs(connect_tool, primary_connection)
                await connect_tool.ainvoke(kwargs)
                logger.info(
                    f"SQLcl MCP: auto-connected to '{primary_connection}' "
                    f"(kwargs={list(kwargs)})"
                )
            except Exception as exc:
                logger.warning(
                    f"Could not auto-connect to '{primary_connection}'. "
                    f"The agent will need to call `connect` manually. "
                    f"Cause: {exc}. "
                    f"Quick fix: in a terminal run "
                    f"`{settings.sqlcl_path} /NOLOG` then "
                    f"`conn -save {primary_connection} -savepwd <user/pwd>@<host:port/service>` "
                    f"and restart."
                )

    tools = list(mcp_tools) + AGENT_TOOLS
    model = build_chat_model(settings)

    @wrap_tool_call
    async def enforce_backend_tool_scope(request, handler):
        """Prevent Oracle SQLcl tools from running on non-Oracle profiles.

        The agent is built once at startup, and when SQLcl is enabled it keeps
        MCP tools in the global toolset. For requests pinned to Postgres, those
        Oracle-only tools must be blocked so SQL execution goes through the
        backend-aware guarded tools (`run_select_sql`, catalog helpers).
        """
        profile = get_runtime_connection()
        tool_call = getattr(request, "tool_call", {}) or {}
        name = tool_call.get("name", "")
        if profile is not None and profile.db_type != "oracle" and name in mcp_tool_names:
            return ToolMessage(
                content=(
                    "SQLcl MCP tools are disabled for non-Oracle connections. "
                    "Use `run_select_sql` and schema tools instead."
                ),
                tool_call_id=tool_call.get("id", ""),
            )
        return await handler(request)

    # Surface saved connections in the system prompt so the agent can switch
    # between them when several are configured.
    system_prompt = settings.system_prompt
    if parsed_conns:
        friendly = []
        for conn in parsed_conns:
            profile = connection_doc.get(conn["nombre"])
            if profile is None:
                friendly.append(conn["nombre"])
            else:
                friendly.append(f"{profile.name} ({profile.id})")
        names = ", ".join(friendly)
        default_note = (
            f"The default connection '{primary_connection}' is already open."
            if primary_connection
            else "Call the `connect` tool with one of these names before running SQL."
        )
        system_prompt = (
            f"{system_prompt}\n\n"
            f"### Available Oracle connections\n"
            f"You have a live SQLcl MCP session. Saved connections: {names}.\n"
            f"{default_note} "
            f"Use `run-sql` (or `run-sqlcl`) to execute queries against the "
            f"current connection."
        )
    else:
        system_prompt = (
            f"{system_prompt}\n\n"
            f"### Active SQL backend\n"
            f"The current backend is `{settings.db_backend}` and SQL dialect is "
            f"`{settings.sqlglot_dialect}`. Use the guarded tool `run_select_sql` "
            f"for query execution."
        )

    agent = create_agent(
        model=model,
        tools=tools,
        store=store,
        system_prompt=system_prompt,
        middleware=[
            enforce_backend_tool_scope,
            handle_tool_errors,
            track_active_connection,
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", 20000),
                keep=("messages", 10),
            ),
            ContextEditingMiddleware(
                edits=[ClearToolUsesEdit(trigger=20000, keep=5)],
            ),
            FilesystemMiddleware(
                backend=StoreBackend(
                    namespace=lambda rt: (rt.context["user_id"],)
                ),
                system_prompt=settings.filesystem_prompt,
                tool_token_limit_before_evict=10000,
                human_message_token_limit_before_evict=5000,
            ),
            SkillMiddleware(),
        ],
        checkpointer=checkpointer,
        name="nl2sql_agent",
    )
    return agent, parsed_conns, primary_connection, connect_tool


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_oracle_client(settings)
    app.state.settings = settings
    app.state.chat_rate_limiter = SlidingWindowRateLimiter(
        max_requests=settings.chat_rate_limit_requests,
        window_seconds=settings.chat_rate_limit_window_s,
    )
    store = FileConnectionStore(settings.connection_store_path)
    connection_doc = store.load()
    connection_doc = seed_profiles_from_settings(connection_doc, settings)
    connection_doc = merge_profiles_from_env(connection_doc, settings)
    store.save(connection_doc)
    app.state.connection_store = store
    app.state.connection_store_lock = asyncio.Lock()
    app.state.connection_doc = connection_doc
    app.state.connection_profiles = []
    app.state.agent = None
    app.state.sqlcl_connections = connection_doc.sqlcl_connections()
    app.state.active_connection = None
    app.state.mcp_connect_tool = None
    app.state.connection_switch_lock = asyncio.Lock()

    async with AsyncExitStack() as stack:
        try:
            if settings.db_backend.strip().lower() == "oracle" and settings.sqlcl_path:
                check_for_sqlcl(settings.sqlcl_path)
            agent, parsed_conns, primary_connection, connect_tool = await _build_langgraph_agent(
                app,
                stack,
                settings,
                connection_doc,
            )
            app.state.agent = agent
            app.state.sqlcl_connections = parsed_conns or connection_doc.sqlcl_connections()
            app.state.active_connection = (
                primary_connection
                or connection_doc.default_connection_id
            )
            app.state.mcp_connect_tool = connect_tool
            _refresh_connection_state(app, connection_doc)
            logger.info("LangGraph agent ready. /api/v1/chat-stream endpoint active.")
        except Exception as exc:
            logger.warning(
                f"LangGraph agent build failed; chat endpoints will return 503. "
                f"Cause: {exc}"
            )
            app.state.agent = None
            app.state.active_connection = connection_doc.default_connection_id
            _refresh_connection_state(app, connection_doc)
        yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _dsn_target(cadena: str) -> str:
    """Return the host portion of a SQLcl saved-connection string.

    Input is ``user/pass@host:port/service``; we drop everything before the
    last ``@`` so the GUI can show ``host:port/service`` without ever
    exposing the password.
    """
    if not cadena:
        return ""
    return cadena.rsplit("@", 1)[-1].strip()


def _refresh_connection_state(
    app: FastAPI,
    connection_doc: ConnectionStoreDocument,
) -> None:
    active = getattr(app.state, "active_connection", None)
    app.state.connection_doc = connection_doc
    app.state.connection_profiles = connection_doc.public_profiles(active_id=active)
    app.state.sqlcl_connections = connection_doc.sqlcl_connections()


@app.get("/api/v1/connections/")
def list_connections(request: Request) -> dict:
    saved = getattr(request.app.state, "connection_profiles", []) or []
    active = getattr(request.app.state, "active_connection", None)
    agent_ready = getattr(request.app.state, "agent", None) is not None
    default_id = getattr(request.app.state, "connection_doc", ConnectionStoreDocument()).default_connection_id
    return {
        "agent_ready": agent_ready,
        "active": active,
        "default_connection_id": default_id,
        "connections": saved,
    }


def _require_agent(request: Request):
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "agent_disabled",
                "detail": "Configure DB_BACKEND + database credentials and "
                "ANTHROPIC_API_KEY/OPENAI_API_KEY (+ model), then restart "
                "to enable /api/v1/chat-stream and /gui.",
            },
        )
    return agent


def _enforce_chat_rate_limit(request: Request, key: str) -> None:
    settings: Settings = app.state.settings
    if not settings.chat_rate_limit_enabled:
        return
    retry_after = app.state.chat_rate_limiter.check(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "detail": "Too many chat requests. Retry later.",
                "retry_after_s": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )


async def activate_request_connection(
    app: FastAPI,
    mensaje: UserMessage,
):
    """Resolve the connection profile for a chat request and switch SQLcl MCP.

    Shared by the HTTP endpoint (`/api/v1/chat-stream`) and the NiceGUI chat
    (`/gui`) so both paths follow the same activation rules: the user-picked
    `connection_id` (or the document default) determines which profile is
    used, Oracle profiles trigger an SQLcl-MCP `connect` switch before the
    stream starts, and app.state.active_connection is updated for the UI.

    Returns the resolved ``DbConnectionProfile`` (or ``None`` when no profile
    is configured). Callers MUST wrap the stream with ``set_runtime_connection``
    / ``reset_runtime_connection`` so backend-aware tools see the active scope.
    """
    connection_doc: ConnectionStoreDocument = getattr(
        app.state,
        "connection_doc",
        ConnectionStoreDocument(),
    )
    requested_id = (mensaje.connection_id or "").strip()
    chosen_profile = connection_doc.get(requested_id)
    if chosen_profile is None:
        chosen_profile = connection_doc.get(connection_doc.default_connection_id)
    if chosen_profile is None:
        return None

    previous_active = getattr(app.state, "active_connection", None)
    connect_tool = getattr(app.state, "mcp_connect_tool", None)
    if chosen_profile.db_type == "oracle" and connect_tool is not None:
        target_connection = chosen_profile.id
        if target_connection != previous_active:
            async with app.state.connection_switch_lock:
                if getattr(app.state, "active_connection", None) != target_connection:
                    kwargs = _connect_tool_kwargs(connect_tool, target_connection)
                    await connect_tool.ainvoke(kwargs)
                    app.state.active_connection = target_connection
                    _refresh_connection_state(app, connection_doc)
                    logger.info(
                        f"SQLcl MCP: switched active connection to '{target_connection}' "
                        f"before chat request."
                    )
    app.state.active_connection = chosen_profile.id
    _refresh_connection_state(app, connection_doc)
    return chosen_profile


@app.post("/api/v1/chat-stream/")
async def chat_stream(request: Request, mensaje: UserMessage):
    agent = _require_agent(request)
    _enforce_chat_rate_limit(request, f"chat:{mensaje.user_id}")
    chosen_profile = await activate_request_connection(request.app, mensaje)
    logger.info(
        f"Recibida petición de usuario {mensaje.user_id} en thread "
        f"{mensaje.thread_id}, mensaje: {mensaje.message}"
    )

    async def _stream():
        token = set_runtime_connection(chosen_profile)
        try:
            async for chunk in stream_agent_response(agent, mensaje, chosen_profile):
                yield chunk
        finally:
            reset_runtime_connection(token)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
    )


def _request_rate_limit_key(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown-client"
    if request.client and request.client.host:
        return request.client.host
    return "unknown-client"


# NiceGUI mount: only attach the chat UI when SQLcl is configured. We import
# lazily so importing main.py inside unit tests does not pull nicegui.
def _maybe_mount_nicegui(app: FastAPI) -> None:
    try:
        from nicegui import ui

        from nl2sql_agent.web import init_nicegui

        settings = get_settings()
        init_nicegui(app)
        ui.run_with(
            app=app,
            title="NL2SQL Agent",
            storage_secret=settings.nicegui_storage_secret,
            mount_path="/gui",
        )
        logger.info("NiceGUI montado en /gui")
    except Exception as exc:
        logger.warning(f"NiceGUI no se pudo montar: {exc}")


_maybe_mount_nicegui(app)

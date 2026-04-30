from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from threading import Lock
from typing import Any

import oracledb
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from nl2sql_agent.executor import (
    NonSelectSqlError,
    classify_oracle_error,
    cure_sql_against_schema,
    is_safe_retry_class,
    run_select,
)
from nl2sql_agent.generator import agent_response, stream_agent_response
from nl2sql_agent.llm import SqlGenerator
from nl2sql_agent.mcp_bridge import (
    check_for_sqlcl,
    parse_connection_string,
    sqlcl_init_config,
)
from nl2sql_agent.models import UserMessage
from nl2sql_agent.oracle_catalog import verify_question_objects_against_catalog
from nl2sql_agent.schema_loader import SchemaContext, load_schema
from nl2sql_agent.settings import Settings, get_settings


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    elapsed_ms: int
    """When schema retrieval is on: Oracle table names included in the LLM schema block; else null."""
    schema_tables_in_prompt: list[str] | None = None


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
    mode = settings.oracle_client_mode.strip().lower()
    if mode != "thick":
        return

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


async def _build_langgraph_agent(stack: AsyncExitStack, settings: Settings):
    """Build the LangGraph agent inside the lifespan AsyncExitStack.

    Returns the compiled agent. Raises on any setup failure so the caller
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

    os.makedirs("memory", exist_ok=True)

    checkpointer = await stack.enter_async_context(
        AsyncSqliteSaver.from_conn_string("./memory/checkpoints.sqlite")
    )
    await checkpointer.setup()

    store = await stack.enter_async_context(
        AsyncSqliteStore.from_conn_string("./memory/store.sqlite")
    )
    await store.setup()

    parsed_conns = parse_connection_string(settings.sqlcl_connections)
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
    primary_connection: str | None = None
    if connect_tool is not None and parsed_conns:
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

    # Surface saved connections in the system prompt so the agent can switch
    # between them when several are configured.
    system_prompt = settings.system_prompt
    if parsed_conns:
        names = ", ".join(c["nombre"] for c in parsed_conns)
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

    agent = create_agent(
        model=model,
        tools=tools,
        store=store,
        system_prompt=system_prompt,
        middleware=[
            handle_tool_errors,
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
    return agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_oracle_client(settings)
    schema_ctx = load_schema(
        settings.schema_path,
        prompt_char_budget=settings.schema_prompt_char_budget,
    )
    sql_generator = SqlGenerator(settings)
    app.state.settings = settings
    app.state.schema_ctx = schema_ctx
    app.state.sql_generator = sql_generator
    app.state.ask_rate_limiter = SlidingWindowRateLimiter(
        max_requests=settings.ask_rate_limit_requests,
        window_seconds=settings.ask_rate_limit_window_s,
    )
    app.state.agent = None

    async with AsyncExitStack() as stack:
        if settings.sqlcl_path:
            try:
                check_for_sqlcl(settings.sqlcl_path)
                app.state.agent = await _build_langgraph_agent(stack, settings)
                logger.info("LangGraph agent ready. /api/v1/chat* endpoints active.")
            except Exception as exc:
                logger.warning(
                    f"LangGraph agent build failed; chat endpoints will return 503. "
                    f"Cause: {exc}"
                )
                app.state.agent = None
        else:
            logger.info(
                "SQLCL_PATH not set; LangGraph agent disabled. /ask still works."
            )
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


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, request: Request) -> AskResponse:
    settings: Settings = app.state.settings
    schema_ctx: SchemaContext = app.state.schema_ctx
    sql_generator: SqlGenerator = app.state.sql_generator
    ask_rate_limiter: SlidingWindowRateLimiter = app.state.ask_rate_limiter

    if settings.ask_rate_limit_enabled:
        key = _request_rate_limit_key(request)
        retry_after = ask_rate_limiter.check(key)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limited",
                    "detail": "Too many /ask requests. Retry later.",
                    "retry_after_s": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

    missing_msg = verify_question_objects_against_catalog(
        payload.question,
        schema_ctx.known_object_names(),
        settings,
    )
    if missing_msg:
        raise HTTPException(status_code=404, detail=missing_msg)

    try:
        sql, tables_meta = sql_generator.generate_sql(payload.question, schema_ctx)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "llm_failed", "detail": str(exc)},
        ) from exc

    retry_budget = (
        max(0, settings.sql_repair_max_attempts)
        if settings.sql_repair_enabled
        else 0
    )
    last_non_select_exc: NonSelectSqlError | None = None
    last_db_exc: oracledb.Error | None = None
    last_error_class = "other"

    for attempt in range(retry_budget + 1):
        execution_sql = sql
        if settings.sql_cure_validate_enabled:
            try:
                execution_sql = cure_sql_against_schema(execution_sql, schema_ctx)
            except NonSelectSqlError as exc:
                last_non_select_exc = exc
                if attempt < retry_budget and settings.sql_repair_enabled:
                    sql = sql_generator.repair_sql(
                        payload.question,
                        execution_sql,
                        str(exc),
                        schema_ctx,
                    )
                    continue
                break

        try:
            result = run_select(execution_sql, settings)
        except NonSelectSqlError as exc:
            last_non_select_exc = exc
            if attempt < retry_budget and settings.sql_repair_enabled:
                sql = sql_generator.repair_sql(
                    payload.question,
                    execution_sql,
                    str(exc),
                    schema_ctx,
                )
                continue
            break
        except oracledb.Error as exc:
            last_db_exc = exc
            last_error_class = classify_oracle_error(exc)
            if (
                attempt < retry_budget
                and settings.sql_repair_enabled
                and is_safe_retry_class(last_error_class)
            ):
                sql = sql_generator.repair_sql(
                    payload.question,
                    execution_sql,
                    f"{last_error_class}: {exc}",
                    schema_ctx,
                )
                continue
            break
        else:
            return AskResponse(
                sql=execution_sql,
                schema_tables_in_prompt=tables_meta,
                **result,
            )

    if last_non_select_exc is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "non_select_sql",
                "detail": str(last_non_select_exc),
            },
        ) from last_non_select_exc

    if last_db_exc is not None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "db_error",
                "class": last_error_class,
                "detail": "Database execution failed.",
            },
        ) from last_db_exc

    raise HTTPException(
        status_code=500,
        detail={"error": "unhandled_execution_path"},
    )


def _require_agent(request: Request):
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "agent_disabled",
                "detail": "Set SQLCL_PATH (and ANTHROPIC_API_KEY/OPENAI_API_KEY + model) "
                "and restart to enable /api/v1/chat*.",
            },
        )
    return agent


def _enforce_chat_rate_limit(request: Request, key: str) -> None:
    settings: Settings = app.state.settings
    if not settings.ask_rate_limit_enabled:
        return
    retry_after = app.state.ask_rate_limiter.check(key)
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


@app.post("/api/v1/chat/")
async def chat(request: Request, mensaje: UserMessage):
    agent = _require_agent(request)
    _enforce_chat_rate_limit(request, f"chat:{mensaje.user_id}")
    try:
        return {"reply": await agent_response(agent, mensaje)}
    except Exception as exc:
        logger.exception(f"Error procesando petición: {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error en el motor del agente: {exc}"
        )


@app.post("/api/v1/chat-stream/")
async def chat_stream(request: Request, mensaje: UserMessage):
    agent = _require_agent(request)
    _enforce_chat_rate_limit(request, f"chat:{mensaje.user_id}")
    logger.info(
        f"Recibida petición de usuario {mensaje.user_id} en thread "
        f"{mensaje.thread_id}, mensaje: {mensaje.message}"
    )
    return StreamingResponse(
        stream_agent_response(agent, mensaje),
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
    settings = get_settings()
    if not settings.sqlcl_path:
        return
    try:
        from nicegui import ui

        from nl2sql_agent.web import init_nicegui

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

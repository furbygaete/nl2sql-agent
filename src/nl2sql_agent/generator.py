"""SSE streaming and blocking response helpers for the LangGraph agent.

Ported from oracle-sqlcl-chat/app/generator.py with two fixes:
  * agent_response is awaited correctly when called from a route.
  * langsmith.@traceable is imported behind a guard so the module loads
    without langsmith installed.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import openai
from loguru import logger

from .models import UserMessage

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

try:  # pragma: no cover - tracing is optional
    from langsmith import traceable as _traceable

    def traceable(fn):
        return _traceable(fn)
except Exception:  # pragma: no cover

    def traceable(fn):
        return fn


@traceable
async def stream_agent_response(agent: CompiledStateGraph, mensaje: UserMessage):
    logger.info(f"Mensaje recibido: {mensaje.message}")
    yield f"data: {json.dumps({'type': 'info', 'content': 'Conectado. Analizando petición...'})}\n\n"

    try:
        async for chunk, metadata in agent.astream(
            input={"messages": [{"role": "user", "content": mensaje.message}]},
            config={
                "configurable": {
                    "thread_id": f"{mensaje.user_id}:{mensaje.thread_id}"
                }
            },
            stream_mode="messages",
            context={"user_id": mensaje.user_id},
        ):
            if metadata and metadata.get("lc_source") == "summarization":
                continue
            if (
                hasattr(chunk, "additional_kwargs")
                and chunk.additional_kwargs.get("lc_source") == "summarization"
            ):
                continue

            texto_chunk = ""
            if hasattr(chunk, "content") and chunk.content:
                if isinstance(chunk.content, str):
                    texto_chunk = chunk.content
                elif isinstance(chunk.content, list):
                    # Walk every block. Models may interleave thinking + text
                    # (e.g. Claude returns [{type:thinking,...},{type:text,...}]),
                    # so picking content[0] alone silently drops the answer.
                    parts: list[str] = []
                    for item in chunk.content:
                        if isinstance(item, dict):
                            if isinstance(item.get("text"), str):
                                parts.append(item["text"])
                            elif item.get("type") == "text" and isinstance(
                                item.get("value"), str
                            ):
                                parts.append(item["value"])
                        elif hasattr(item, "text") and isinstance(item.text, str):
                            parts.append(item.text)
                    texto_chunk = "".join(parts)

            es_mensaje_herramienta = (
                getattr(chunk, "type", "") == "tool"
                or "ToolMessage" in chunk.__class__.__name__
            )

            if es_mensaje_herramienta:
                if texto_chunk:
                    yield f"data: {json.dumps({'type': 'tool_result', 'content': texto_chunk})}\n\n"
            else:
                if texto_chunk:
                    yield f"data: {json.dumps({'type': 'text', 'content': texto_chunk})}\n\n"

                if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    nombres_herramientas = [
                        (
                            tc.get("name")
                            if isinstance(tc, dict)
                            else getattr(tc, "name", "tool")
                        )
                        for tc in chunk.tool_calls
                    ]
                    yield (
                        f"data: {json.dumps({'type': 'tool', 'tools': nombres_herramientas, 'content': 'Consultando base de datos...'})}\n\n"
                    )

    except openai.BadRequestError as exc:
        logger.exception(f"OpenAI BadRequestError: {exc}")
        api_message = ""
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            api_message = (body.get("error") or {}).get("message", "") or ""
        if not api_message:
            api_message = getattr(exc, "message", "") or str(exc)
        friendly = (
            "The model rejected the request. "
            "This usually means the prompt was too long, contained "
            "an unsupported tool/argument, or hit a content policy. "
            f"Details: {api_message}"
        )
        yield f"data: {json.dumps({'type': 'error', 'kind': 'bad_request', 'content': friendly, 'detail': str(exc)})}\n\n"

    except Exception as exc:
        logger.exception(f"Error en el stream: {exc}")
        yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'content': 'Terminado'})}\n\n"
    logger.success(
        f"Stream finalizado para usuario {mensaje.user_id} en thread {mensaje.thread_id}"
    )


@traceable
async def agent_response(agent: CompiledStateGraph, mensaje: UserMessage) -> str:
    logger.info("Procesando respuesta del agente...")
    response = await agent.ainvoke(
        input={"messages": [{"role": "user", "content": mensaje.message}]},
        config={
            "configurable": {
                "thread_id": f"{mensaje.user_id}:{mensaje.thread_id}"
            }
        },
        context={"user_id": mensaje.user_id},
    )
    last = response["messages"][-1]
    if isinstance(last.content, list) and last.content:
        first = last.content[0]
        if isinstance(first, dict):
            return first.get("text", str(last.content))
        return getattr(first, "text", str(last.content))
    return last.content

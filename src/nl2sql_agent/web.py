"""NiceGUI chat interface mounted at /gui.

Ported from oracle-sqlcl-chat/app/web.py with minor adjustments:
  * Title "NL2SQL Agent" instead of "Oracle CHAT".
  * Drops the spurious `preferences={}` kwarg the source passed to
    UserMessage (the model doesn't accept it).
  * English placeholder text.
"""
from __future__ import annotations

import json
import uuid

from loguru import logger
from nicegui import app, ui

from .generator import stream_agent_response
from .models import UserMessage


def init_nicegui(fastapi_state) -> None:
    @ui.page("/")
    def main_page() -> None:
        if "user_id" not in app.storage.user:
            app.storage.user["user_id"] = uuid.uuid4().hex
        if "threads" not in app.storage.user:
            app.storage.user["threads"] = ["First Conversation"]
        if "current_thread" not in app.storage.user:
            app.storage.user["current_thread"] = "First Conversation"

        local_state = {"is_processing": False}

        ui.query("body").style("background-color: #f8fafc; color: #1e293b;")

        with ui.column().classes("w-full h-screen p-4 flex flex-col"):
            with ui.card().classes(
                "w-full flex-grow flex flex-col p-0 overflow-hidden "
                "shadow-xl rounded-2xl border border-slate-200"
            ):
                with ui.row().classes(
                    "w-full px-6 py-4 bg-slate-900 text-white items-center "
                    "gap-4 shadow-md z-10"
                ):
                    with ui.row().classes("items-center gap-2 mr-auto"):
                        ui.icon("smart_toy", size="sm").classes("text-blue-400")
                        ui.label("NL2SQL Agent").classes(
                            "text-xl font-bold tracking-wide"
                        )

                    thread_selector = (
                        ui.select(
                            options=app.storage.user["threads"],
                            value=app.storage.user["current_thread"],
                            on_change=lambda e: switch_thread(e.value),
                        )
                        .classes(
                            "w-48 bg-slate-800 text-white rounded "
                            "outline-none border-none"
                        )
                        .props("dense dark standout")
                    )

                    ui.button(icon="add", on_click=lambda: create_new_thread()).props(
                        "flat round color=white"
                    ).tooltip("New conversation")

                scroll_area = ui.scroll_area().classes(
                    "w-full flex-grow p-6 bg-slate-50"
                )
                with scroll_area:
                    chat_box = ui.column().classes("w-full gap-6 pb-4")

            with ui.row().classes("w-full pt-4 gap-3 items-end"):
                msg_input = (
                    ui.input(placeholder="Ask the database…")
                    .classes("flex-grow text-lg bg-white shadow-sm")
                    .props("rounded outlined clearable autogrow")
                )
                send_btn = ui.button(icon="send").props(
                    "round color=primary size=lg shadow-md"
                )

                async def create_new_thread():
                    new_id = f"Session {uuid.uuid4().hex[:4].upper()}"
                    app.storage.user["threads"].append(new_id)
                    app.storage.user["current_thread"] = new_id
                    thread_selector.set_options(app.storage.user["threads"])
                    thread_selector.value = new_id
                    ui.notify(f"New session: {new_id}", type="positive")

                def switch_thread(new_thread_id):
                    app.storage.user["current_thread"] = new_thread_id
                    chat_box.clear()

                async def send():
                    if local_state["is_processing"]:
                        return

                    texto = msg_input.value.strip() if msg_input.value else ""
                    if not texto:
                        return

                    local_state["is_processing"] = True
                    msg_input.disable()
                    send_btn.disable()
                    msg_input.value = ""

                    with chat_box:
                        ui.chat_message(texto, name="You", sent=True).props(
                            'bg-color="blue-6" text-color="white"'
                        ).classes("w-full text-base")

                        bot_container = (
                            ui.chat_message(name="Agent", sent=False)
                            .props('bg-color="grey-2" text-color="grey-10"')
                            .classes("w-full text-base")
                        )

                        with bot_container:
                            with ui.element("div").classes("flex flex-col w-full"):
                                tool_ui_container = ui.row().classes(
                                    "items-center gap-2 text-indigo-600 "
                                    "font-medium py-1 animate-pulse"
                                )
                                with tool_ui_container:
                                    ui.icon("settings", size="xs").classes(
                                        "animate-spin"
                                    )
                                    tool_label = ui.label("Starting analysis…")
                                response_label = ui.markdown("").classes("hidden")

                    scroll_area.scroll_to(percent=1.0)

                    try:
                        usuario_obj = UserMessage(
                            message=texto,
                            user_id=app.storage.user["user_id"],
                            thread_id=app.storage.user["current_thread"],
                        )

                        full_response = ""
                        tool_state = {"name": None, "count": 1}

                        async for chunk_str in stream_agent_response(
                            fastapi_state.state.agent, usuario_obj
                        ):
                            if not chunk_str.startswith("data: "):
                                continue
                            data_str = chunk_str[6:].strip()
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            if data.get("type") == "tool":
                                tool_ui_container.classes(remove="hidden")
                                tool_name = data["tools"][0]
                                if tool_state["name"] == tool_name:
                                    tool_state["count"] += 1
                                else:
                                    tool_state["name"] = tool_name
                                    tool_state["count"] = 1
                                count_text = (
                                    f" (x{tool_state['count']})"
                                    if tool_state["count"] > 1
                                    else ""
                                )
                                tool_label.set_text(
                                    f"Calling: {tool_name}{count_text}"
                                )
                                scroll_area.scroll_to(percent=1.0)
                            elif data.get("type") == "text":
                                tool_ui_container.classes(add="hidden")
                                response_label.classes(remove="hidden")
                                full_response += data["content"]
                                response_label.set_content(full_response)
                                scroll_area.scroll_to(percent=1.0)
                            elif data.get("type") == "error":
                                tool_ui_container.classes(add="hidden")
                                friendly = data.get("content") or "An error occurred while contacting the model."
                                detail = data.get("detail") or friendly
                                logger.error(f"Stream error ({data.get('kind', 'unknown')}): {detail}")
                                ui.run_javascript(
                                    f"console.error({json.dumps('NL2SQL stream error: ' + detail)});"
                                )
                                response_label.classes(remove="hidden")
                                response_label.set_content(f"**⚠️ {friendly}**")
                                ui.notify(friendly, type="negative", timeout=8000, multi_line=True, close_button="OK")
                                scroll_area.scroll_to(percent=1.0)
                                break

                    except Exception as exc:
                        tool_ui_container.classes(add="hidden")
                        ui.notify(f"Error: {exc}", type="negative")
                        logger.exception(f"Error: {exc}")

                    finally:
                        # Always hide the spinner — the stream may have ended
                        # without ever emitting a `text` event (tool-only flows,
                        # extraction misses, etc.) and the spinner would
                        # otherwise stay up forever.
                        tool_ui_container.classes(add="hidden")
                        if not full_response:
                            response_label.classes(remove="hidden")
                            response_label.set_content(
                                "_(no textual response — check the server logs "
                                "for the agent's last message)_"
                            )
                        local_state["is_processing"] = False
                        msg_input.enable()
                        send_btn.enable()
                        msg_input.run_method("focus")
                        scroll_area.scroll_to(percent=1.0)

                msg_input.on("keydown.enter", send)
                send_btn.on_click(send)

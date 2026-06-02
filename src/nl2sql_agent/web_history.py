"""Thread transcript and message rendering helpers."""
from __future__ import annotations

from typing import Any

from nicegui import ui


def get_transcript(storage_user: dict[str, Any], thread_id: str) -> list[dict]:
    return list(storage_user.get("thread_messages", {}).get(thread_id, []))


def save_transcript(storage_user: dict[str, Any], thread_id: str, transcript: list[dict]) -> None:
    thread_messages = dict(storage_user.get("thread_messages", {}))
    thread_messages[thread_id] = transcript
    storage_user["thread_messages"] = thread_messages


def render_user_bubble(chat_box: Any, text: str, escape: Any) -> None:
    with chat_box:
        ui.html(f'<div class="msg user"><div class="bubble">{escape(text)}</div></div>')


def render_bot_bubble(chat_box: Any, markdown_text: str) -> None:
    with chat_box:
        with ui.element("div").classes("msg bot"):
            with ui.element("div").classes("bubble"):
                ui.markdown(markdown_text)

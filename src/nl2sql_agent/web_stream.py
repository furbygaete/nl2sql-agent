"""Streaming UI event helpers for NiceGUI chat responses."""
from __future__ import annotations

import base64
import json
from typing import Any, Callable

from nicegui import ui


def attach_export_download_handlers(
    *,
    csv_download_btn: Any,
    xlsx_download_btn: Any,
    pdf_download_btn: Any,
    export_state: dict[str, Any],
) -> None:
    def _download_file(content_bytes: bytes, mime_type: str, filename: str) -> None:
        if not content_bytes:
            ui.notify("No downloadable data available for this response.", type="warning")
            return
        encoded = base64.b64encode(content_bytes).decode("ascii")
        js = (
            "(() => {"
            "const a = document.createElement('a');"
            f"a.href = 'data:{mime_type};base64,{encoded}';"
            f"a.download = {json.dumps(filename)};"
            "document.body.appendChild(a);"
            "a.click();"
            "a.remove();"
            "})();"
        )
        ui.run_javascript(js)

    if csv_download_btn is not None:
        csv_download_btn.on(
            "click",
            lambda _e: _download_file(
                export_state["csv_text"].encode("utf-8"),
                "text/csv;charset=utf-8",
                f"{export_state['filename_base']}.csv",
            ),
        )
    if xlsx_download_btn is not None:
        xlsx_download_btn.on(
            "click",
            lambda _e: _download_file(
                export_state["xlsx_bytes"],
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                f"{export_state['filename_base']}.xlsx",
            ),
        )
    if pdf_download_btn is not None:
        pdf_download_btn.on(
            "click",
            lambda _e: _download_file(
                export_state["pdf_bytes"],
                "application/pdf",
                f"{export_state['filename_base']}.pdf",
            ),
        )


def handle_tool_result_event(
    *,
    content: str,
    csv_download_wrap: Any,
    export_state: dict[str, Any],
    parse_tabular_tool_result: Callable[[str], tuple[list[str], list[list[Any]]] | None],
    build_csv_text: Callable[[list[str], list[list[Any]]], str],
    build_xlsx_bytes: Callable[[list[str], list[list[Any]]], bytes],
    build_pdf_bytes: Callable[[list[str], list[list[Any]]], bytes],
    filename_seed: str,
) -> None:
    parsed = parse_tabular_tool_result(content)
    if parsed and csv_download_wrap is not None:
        columns, rows = parsed
        export_state["csv_text"] = build_csv_text(columns, rows)
        export_state["xlsx_bytes"] = build_xlsx_bytes(columns, rows)
        export_state["pdf_bytes"] = build_pdf_bytes(columns, rows)
        export_state["filename_base"] = filename_seed
        csv_download_wrap.style("display: block;")


def handle_image_event(
    *,
    data: dict[str, Any],
    bot_inner: Any,
    thinking_el: Any,
    scroll_area: Any,
    escape: Callable[[str], str],
) -> bool:
    image_b64 = data.get("data")
    image_mime = data.get("mime") or "image/png"
    if not image_b64:
        return False

    thinking_el.style("display: none;")
    spec = data.get("spec") or {}
    caption = ""
    if isinstance(spec, dict):
        chart_type = spec.get("chart_type")
        x_col = spec.get("x")
        y_col = spec.get("y")
        if chart_type and x_col and y_col:
            caption = (
                f'<div class="chart-caption">{escape(str(chart_type).upper())}: '
                f'{escape(str(y_col))} by {escape(str(x_col))}</div>'
            )
    with bot_inner:
        ui.html(
            f'<div class="chart-image-wrap">'
            f'<img src="data:{escape(image_mime)};base64,{image_b64}" alt="Generated data chart" />'
            f"{caption}</div>"
        )
    scroll_area.scroll_to(percent=1.0)
    return True

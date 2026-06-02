"""Formatting helpers used by the NiceGUI web interface."""
from __future__ import annotations


def apply_theme(dark, mode: str) -> None:
    if mode == "dark":
        dark.value = True
    elif mode == "light":
        dark.value = False
    else:
        dark.value = None


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

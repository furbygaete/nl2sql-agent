"""NiceGUI chat interface mounted at /gui.

Modernized UI per docs/UI_MODERNIZATION.md:
- Token-based design system (Light / Auto / Dark) via :root + .body--dark
- Sidebar (threads + theme switcher) + topbar + centered chat + pill composer
- Empty state with prefill suggestions, 3-dot thinking indicator
- Inline SVG icons, ARIA labels, focus halos, mobile drawer < 768 px

Preserves the SSE streaming contract from generator.stream_agent_response
(types: info, text, tool, tool_result, error, done) and the
app.storage.user keys used previously (user_id, threads, current_thread).
"""
from __future__ import annotations

import json
import uuid

from loguru import logger
from nicegui import app, ui

from .generator import stream_agent_response
from .models import UserMessage


_HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {
  --bg:#F6F7FB; --surface:#FFFFFF; --surface-2:#F1F5F9; --surface-3:#E2E8F0;
  --border:#E5E7EB; --border-strong:#CBD5E1;
  --text:#0F172A; --text-2:#475569; --text-3:#94A3B8;
  --primary:#4F46E5; --primary-hover:#4338CA; --primary-soft:#EEF2FF;
  --accent:#0891B2; --success:#059669; --danger:#DC2626;
  --radius-sm:8px; --radius:12px; --radius-lg:16px; --radius-xl:20px;
  --shadow-sm:0 1px 2px rgba(15,23,42,.04),0 1px 3px rgba(15,23,42,.06);
  --shadow-md:0 4px 12px rgba(15,23,42,.06),0 2px 4px rgba(15,23,42,.04);
  --shadow-lg:0 24px 48px -12px rgba(15,23,42,.18);
}
.body--dark {
  --bg:#0B0F17; --surface:#111827; --surface-2:#1F2937; --surface-3:#273344;
  --border:#1F2937; --border-strong:#334155;
  --text:#F1F5F9; --text-2:#CBD5E1; --text-3:#64748B;
  --primary:#818CF8; --primary-hover:#A5B4FC; --primary-soft:rgba(99,102,241,.12);
  --accent:#22D3EE; --success:#34D399; --danger:#F87171;
  --shadow-sm:0 1px 2px rgba(0,0,0,.30);
  --shadow-md:0 6px 16px rgba(0,0,0,.35);
  --shadow-lg:0 24px 48px -12px rgba(0,0,0,.55);
}

* { box-sizing: border-box; }

html, body, .nicegui-content {
  margin: 0; padding: 0;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
}
.nicegui-content { padding: 0 !important; gap: 0 !important; }

code, kbd, pre, .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }

/* ---------- App shell ---------- */
.app-shell {
  display: flex;
  width: 100vw;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg);
}

/* ---------- Sidebar ---------- */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: transform .25s ease;
}
.sidebar-header {
  padding: 18px 18px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  width: 32px; height: 32px;
  border-radius: 9px;
  background: var(--primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}
.brand-text { display: flex; flex-direction: column; line-height: 1.1; }
.brand-name {
  font-weight: 600;
  font-size: 14.5px;
  letter-spacing: -0.01em;
  color: var(--text);
}
.brand-sub {
  font-size: 10.5px;
  color: var(--text-3);
  letter-spacing: .06em;
  text-transform: uppercase;
  margin-top: 2px;
}
.new-chat-btn {
  margin: 6px 14px 12px;
  padding: 10px 14px;
  background: var(--primary);
  color: white;
  border: 0;
  border-radius: var(--radius);
  font: inherit;
  font-weight: 500;
  font-size: 13.5px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  transition: background .15s;
  box-shadow: var(--shadow-sm);
}
.new-chat-btn:hover { background: var(--primary-hover); }
.new-chat-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 25%, transparent);
}

.threads {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px 12px;
}
.threads-label {
  padding: 10px 10px 6px;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-3);
  font-weight: 600;
}
.thread-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  margin: 1px 0;
  border-radius: var(--radius-sm);
  color: var(--text-2);
  cursor: pointer;
  font-size: 13.5px;
  border: 0;
  background: transparent;
  width: 100%;
  text-align: left;
  font-family: inherit;
  transition: background .12s, color .12s;
}
.thread-item:hover {
  background: var(--surface-2);
  color: var(--text);
}
.thread-item.active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 500;
}
.thread-item:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent);
}

.sidebar-footer {
  padding: 12px 14px 16px;
  border-top: 1px solid var(--border);
}
.theme-seg {
  display: flex;
  background: var(--surface-2);
  border-radius: 10px;
  padding: 3px;
  gap: 2px;
}
.theme-seg button {
  flex: 1;
  padding: 6px 8px;
  border: 0;
  background: transparent;
  border-radius: 7px;
  color: var(--text-2);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  transition: background .15s, color .15s;
}
.theme-seg button:hover { color: var(--text); }
.theme-seg button.active {
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-sm);
}
.theme-seg button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent);
}

/* ---------- Main column ---------- */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg);
}
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 22px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.topbar-title {
  font-size: 14.5px;
  font-weight: 600;
  margin: 0;
  color: var(--text);
  letter-spacing: -0.005em;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 18%, transparent);
}
.spacer { flex: 1; }
.icon-btn {
  width: 34px; height: 34px;
  border-radius: 9px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background .12s, color .12s;
}
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
.icon-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent);
}
.hamburger { display: none; }

/* ---------- Chat area ---------- */
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  background: var(--bg);
  width: 100%;
}
.chat-scroll .q-scrollarea__content {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.chat-inner {
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  padding: 28px 22px 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* Empty state */
.empty {
  margin-top: 6vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 14px;
}
.empty .glyph {
  width: 56px; height: 56px;
  border-radius: 16px;
  background: var(--primary-soft);
  color: var(--primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.empty h2 {
  font-size: 22px;
  font-weight: 600;
  margin: 0;
  color: var(--text);
  letter-spacing: -0.01em;
}
.empty p {
  margin: 0;
  color: var(--text-2);
  font-size: 14px;
  max-width: 460px;
  line-height: 1.55;
}
.suggestions {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  max-width: 600px;
}
.suggestion {
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  font: inherit;
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
  transition: background .15s, border-color .15s, color .15s, transform .15s;
}
.suggestion:hover {
  background: var(--surface-2);
  border-color: var(--border-strong);
  color: var(--text);
}
.suggestion:focus-visible {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 18%, transparent);
}

/* ---------- Messages ---------- */
.msg {
  display: flex;
  gap: 12px;
  animation: msg-in .22s ease both;
}
.msg.user { justify-content: flex-end; }
.bubble {
  max-width: 78%;
  padding: 12px 16px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-wrap: break-word;
}
.msg.user .bubble {
  background: var(--primary);
  color: white;
  border-color: transparent;
  border-bottom-right-radius: 4px;
}
.msg.bot .bubble { border-bottom-left-radius: 4px; }
.bubble :is(p, ul, ol, pre):first-child { margin-top: 0; }
.bubble :is(p, ul, ol, pre):last-child { margin-bottom: 0; }
.bubble code {
  background: var(--surface-2);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12.5px;
}
.bubble pre {
  background: var(--surface-2);
  padding: 10px 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 12.5px;
  margin: 8px 0;
}

/* Thinking indicator */
.thinking {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  color: var(--text-2);
  font-size: 13px;
  align-self: flex-start;
}
.thinking code {
  background: var(--surface-2);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: var(--text);
}
.thinking .dots { display: inline-flex; gap: 4px; }
.thinking .dots span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--primary);
  display: inline-block;
  animation: dot-bounce 1.2s infinite ease-in-out;
}
.thinking .dots span:nth-child(2) { animation-delay: .15s; }
.thinking .dots span:nth-child(3) { animation-delay: .30s; }

.error-bubble {
  background: color-mix(in srgb, var(--danger) 8%, var(--surface));
  border: 1px solid color-mix(in srgb, var(--danger) 35%, var(--border));
  color: var(--text);
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(.6); opacity: .4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ---------- Composer ---------- */
.composer-wrap {
  background: var(--bg);
  padding: 14px 22px 22px;
  border-top: 1px solid transparent;
}
.composer {
  max-width: 820px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xl);
  padding: 8px 8px 8px 16px;
  transition: border-color .15s, box-shadow .15s;
}
.composer:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 18%, transparent);
}
.composer .composer-input { flex: 1; min-width: 0; }
/* Flatten Quasar's input chrome inside the pill */
.composer .q-field { background: transparent !important; padding: 0 !important; }
.composer .q-field__inner,
.composer .q-field__control,
.composer .q-field__control::before,
.composer .q-field__control::after {
  background: transparent !important;
  box-shadow: none !important;
  border: 0 !important;
  min-height: 36px !important;
}
.composer .q-field__native,
.composer .composer-textarea {
  font-family: 'Inter', sans-serif !important;
  font-size: 14.5px !important;
  color: var(--text) !important;
  padding: 6px 0 !important;
  line-height: 1.5 !important;
  resize: none !important;
}
.composer .q-field__native::placeholder,
.composer .composer-textarea::placeholder { color: var(--text-3) !important; }

.send-btn {
  width: 38px; height: 38px;
  border: 0;
  border-radius: 12px;
  background: var(--primary);
  color: white;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background .15s, transform .1s;
}
.send-btn:hover { background: var(--primary-hover); }
.send-btn:active { transform: scale(.96); }
.send-btn:disabled { opacity: .4; cursor: not-allowed; }
.send-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 30%, transparent);
}

/* ---------- Mobile drawer ---------- */
.scrim {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(15,23,42,.45);
  z-index: 40;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 50;
    transform: translateX(-100%);
    box-shadow: var(--shadow-lg);
  }
  .sidebar.open { transform: translateX(0); }
  .scrim.open { display: block; }
  .hamburger { display: inline-flex; }
  .chat-inner { padding: 18px 14px 28px; }
  .composer-wrap { padding: 10px 14px 16px; }
  .suggestions { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .001ms !important;
  }
}
</style>
"""

# Inline SVG icons (single stroke width, currentColor — recolor with text).
_ICON_PLUS = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>'
_ICON_MENU = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>'
_ICON_TRASH = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>'
_ICON_SUN = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>'
_ICON_MOON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
_ICON_AUTO = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M8 22h8M12 18v4"/></svg>'
_ICON_SEND = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>'
_ICON_DB = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>'
_ICON_BRAND = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M4 12h10M4 17h16"/><circle cx="19" cy="12" r="2"/></svg>'

_DEFAULT_THREAD = "First Conversation"

_SUGGESTIONS = [
    "List the 10 most recently hired employees.",
    "Show all tables in the schema and their row counts.",
    "What columns does the EMPLOYEES table have?",
    "Top 5 departments by total salary.",
]


def init_nicegui(fastapi_state) -> None:
    @ui.page("/")
    def main_page() -> None:
        ui.add_head_html(_HEAD_HTML)

        if "user_id" not in app.storage.user:
            app.storage.user["user_id"] = uuid.uuid4().hex
        if "threads" not in app.storage.user:
            app.storage.user["threads"] = [_DEFAULT_THREAD]
        if "current_thread" not in app.storage.user:
            app.storage.user["current_thread"] = _DEFAULT_THREAD
        if "theme" not in app.storage.user:
            app.storage.user["theme"] = "system"

        local_state = {"is_processing": False}

        dark = ui.dark_mode()
        _apply_theme(dark, app.storage.user["theme"])

        with ui.element("div").classes("app-shell"):
            scrim = ui.element("div").classes("scrim").props('aria-hidden="true"')
            sidebar = ui.element("aside").classes("sidebar").props('aria-label="Conversations"')

            with sidebar:
                with ui.element("div").classes("sidebar-header"):
                    with ui.element("div").classes("brand-mark"):
                        ui.html(_ICON_BRAND)
                    with ui.element("div").classes("brand-text"):
                        ui.html('<span class="brand-name">NL2SQL Agent</span>')
                        ui.html('<span class="brand-sub">Oracle • Read-only</span>')

                new_chat_btn = ui.element("button").classes("new-chat-btn")
                new_chat_btn.props('type="button" aria-label="Start new conversation"')
                with new_chat_btn:
                    ui.html(_ICON_PLUS)
                    ui.html("<span>New conversation</span>")

                ui.html('<div class="threads-label">Conversations</div>')
                threads_container = ui.element("nav").classes("threads")
                threads_container.props('aria-label="Conversation list"')

                with ui.element("div").classes("sidebar-footer"):
                    theme_seg = ui.element("div").classes("theme-seg").props('role="group" aria-label="Theme"')
                    with theme_seg:
                        btn_light = ui.element("button").props('type="button" aria-label="Light theme"')
                        with btn_light:
                            ui.html(_ICON_SUN)
                            ui.html("<span>Light</span>")
                        btn_auto = ui.element("button").props('type="button" aria-label="Auto theme"')
                        with btn_auto:
                            ui.html(_ICON_AUTO)
                            ui.html("<span>Auto</span>")
                        btn_dark = ui.element("button").props('type="button" aria-label="Dark theme"')
                        with btn_dark:
                            ui.html(_ICON_MOON)
                            ui.html("<span>Dark</span>")

            main = ui.element("main").classes("main")
            with main:
                with ui.element("header").classes("topbar"):
                    hamburger = ui.element("button").classes("icon-btn hamburger")
                    hamburger.props('type="button" aria-label="Open conversations"')
                    with hamburger:
                        ui.html(_ICON_MENU)

                    title = ui.element("h1").classes("topbar-title")
                    with title:
                        ui.html('<span class="status-dot" aria-hidden="true"></span>')
                        ui.html('<span>NL2SQL Agent</span>')

                    ui.element("div").classes("spacer")

                    clear_btn = ui.element("button").classes("icon-btn")
                    clear_btn.props('type="button" aria-label="Clear conversation" title="Clear conversation"')
                    with clear_btn:
                        ui.html(_ICON_TRASH)

                scroll_area = ui.scroll_area().classes("chat-scroll")
                with scroll_area:
                    chat_inner = ui.element("div").classes("chat-inner")
                    with chat_inner:
                        empty_container = ui.element("div").classes("empty")
                        with empty_container:
                            with ui.element("div").classes("glyph"):
                                ui.html(_ICON_DB)
                            ui.html("<h2>Ask the database</h2>")
                            ui.html(
                                "<p>Natural-language questions become read-only Oracle SQL. "
                                "Try one of these to get started.</p>"
                            )
                            suggestions = ui.element("div").classes("suggestions")

                        chat_box = ui.element("div").classes("chat-box")
                        chat_box.style("display: flex; flex-direction: column; gap: 18px;")

                with ui.element("div").classes("composer-wrap"):
                    composer = ui.element("div").classes("composer")
                    with composer:
                        msg_input = (
                            ui.input(placeholder="Ask anything about the database…")
                            .props('borderless dense autogrow input-class="composer-textarea" aria-label="Message"')
                            .classes("composer-input")
                        )
                        send_btn = ui.element("button").classes("send-btn")
                        send_btn.props('type="button" aria-label="Send message"')
                        with send_btn:
                            ui.html(_ICON_SEND)

        # ----- helpers -----

        def render_threads() -> None:
            threads_container.clear()
            current = app.storage.user.get("current_thread")
            with threads_container:
                for tid in app.storage.user.get("threads", []):
                    btn = ui.element("button").classes("thread-item")
                    btn.props(f'type="button" aria-label="Open {tid}"')
                    if tid == current:
                        btn.classes(add="active")
                    with btn:
                        ui.html(
                            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
                            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                            'stroke-linejoin="round" aria-hidden="true">'
                            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
                            '</svg>'
                        )
                        ui.html(f"<span>{_escape(tid)}</span>")
                    btn.on("click", lambda _e, t=tid: switch_thread(t))

        def render_suggestions() -> None:
            suggestions.clear()
            with suggestions:
                for text in _SUGGESTIONS:
                    s = ui.element("button").classes("suggestion")
                    s.props(f'type="button" aria-label="Use suggestion: {text}"')
                    with s:
                        ui.html(f"<span>{_escape(text)}</span>")
                    s.on("click", lambda _e, t=text: prefill_and_send(t))

        def update_theme_seg() -> None:
            current = app.storage.user.get("theme", "system")
            for b in (btn_light, btn_auto, btn_dark):
                b.classes(remove="active")
            if current == "light":
                btn_light.classes(add="active")
            elif current == "dark":
                btn_dark.classes(add="active")
            else:
                btn_auto.classes(add="active")

        def set_theme(mode: str) -> None:
            app.storage.user["theme"] = mode
            _apply_theme(dark, mode)
            update_theme_seg()

        def show_empty(show: bool) -> None:
            empty_container.style(f"display: {'flex' if show else 'none'};")

        def reset_chat_view() -> None:
            chat_box.clear()
            show_empty(True)

        async def create_new_thread() -> None:
            new_id = f"Session {uuid.uuid4().hex[:4].upper()}"
            app.storage.user["threads"].append(new_id)
            app.storage.user["current_thread"] = new_id
            render_threads()
            reset_chat_view()
            ui.notify(f"New session: {new_id}", type="positive")

        def switch_thread(new_thread_id: str) -> None:
            app.storage.user["current_thread"] = new_thread_id
            render_threads()
            reset_chat_view()
            close_drawer()

        def open_drawer() -> None:
            sidebar.classes(add="open")
            scrim.classes(add="open")

        def close_drawer() -> None:
            sidebar.classes(remove="open")
            scrim.classes(remove="open")

        async def prefill_and_send(text: str) -> None:
            msg_input.value = text
            await send()

        async def send() -> None:
            if local_state["is_processing"]:
                return

            texto = msg_input.value.strip() if msg_input.value else ""
            if not texto:
                return

            local_state["is_processing"] = True
            msg_input.disable()
            send_btn.props('disabled')
            msg_input.value = ""
            show_empty(False)

            full_response = ""
            response_md = None
            thinking_el = None
            label_el = None

            with chat_box:
                user_msg = ui.element("div").classes("msg user")
                with user_msg:
                    bubble = ui.element("div").classes("bubble")
                    with bubble:
                        ui.html(f"<span>{_escape(texto)}</span>")

                bot_msg = ui.element("div").classes("msg bot")
                with bot_msg:
                    bot_inner = ui.element("div").style("display: flex; flex-direction: column; gap: 8px; max-width: 78%;")
                    with bot_inner:
                        thinking_el = ui.element("div").classes("thinking")
                        with thinking_el:
                            ui.html(
                                '<span class="dots" aria-hidden="true">'
                                '<span></span><span></span><span></span>'
                                '</span>'
                            )
                            label_el = ui.html('<span>Starting analysis…</span>')
                        bubble_el = ui.element("div").classes("bubble").style("display: none;")
                        with bubble_el:
                            response_md = ui.markdown("")

            scroll_area.scroll_to(percent=1.0)

            try:
                usuario_obj = UserMessage(
                    message=texto,
                    user_id=app.storage.user["user_id"],
                    thread_id=app.storage.user["current_thread"],
                )

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

                    dtype = data.get("type")

                    if dtype == "tool":
                        thinking_el.style("display: inline-flex;")
                        tool_name = data["tools"][0]
                        if tool_state["name"] == tool_name:
                            tool_state["count"] += 1
                        else:
                            tool_state["name"] = tool_name
                            tool_state["count"] = 1
                        count_text = (
                            f' <span class="mono" style="color:var(--text-3)">×{tool_state["count"]}</span>'
                            if tool_state["count"] > 1
                            else ""
                        )
                        label_el.set_content(
                            f'<span>Calling <code>{_escape(tool_name)}</code>{count_text}</span>'
                        )
                        scroll_area.scroll_to(percent=1.0)

                    elif dtype == "text":
                        thinking_el.style("display: none;")
                        bubble_el.style("display: block;")
                        full_response += data["content"]
                        response_md.set_content(full_response)
                        scroll_area.scroll_to(percent=1.0)

                    elif dtype == "error":
                        thinking_el.style("display: none;")
                        friendly = data.get("content") or "An error occurred while contacting the model."
                        detail = data.get("detail") or friendly
                        logger.error(f"Stream error ({data.get('kind', 'unknown')}): {detail}")
                        ui.run_javascript(
                            f"console.error({json.dumps('NL2SQL stream error: ' + detail)});"
                        )
                        bubble_el.classes(add="error-bubble")
                        bubble_el.style("display: block;")
                        response_md.set_content(f"**⚠ {friendly}**")
                        ui.notify(
                            friendly,
                            type="negative",
                            timeout=8000,
                            multi_line=True,
                            close_button="OK",
                        )
                        scroll_area.scroll_to(percent=1.0)
                        break

            except Exception as exc:
                if thinking_el is not None:
                    thinking_el.style("display: none;")
                ui.notify(f"Error: {exc}", type="negative")
                logger.exception(f"Error: {exc}")

            finally:
                if thinking_el is not None:
                    thinking_el.style("display: none;")
                if not full_response and response_md is not None:
                    bubble_el.style("display: block;")
                    response_md.set_content(
                        "_(no textual response — check the server logs "
                        "for the agent's last message)_"
                    )
                local_state["is_processing"] = False
                msg_input.enable()
                send_btn.props(remove="disabled")
                msg_input.run_method("focus")
                scroll_area.scroll_to(percent=1.0)

        # ----- wire events -----
        new_chat_btn.on("click", lambda _e: create_new_thread())
        clear_btn.on("click", lambda _e: reset_chat_view())
        hamburger.on("click", lambda _e: open_drawer())
        scrim.on("click", lambda _e: close_drawer())
        btn_light.on("click", lambda _e: set_theme("light"))
        btn_auto.on("click", lambda _e: set_theme("system"))
        btn_dark.on("click", lambda _e: set_theme("dark"))
        send_btn.on("click", lambda _e: send())
        msg_input.on("keydown.enter.exact.prevent", send)

        # ----- initial render -----
        render_threads()
        render_suggestions()
        update_theme_seg()


def _apply_theme(dark, mode: str) -> None:
    if mode == "dark":
        dark.value = True
    elif mode == "light":
        dark.value = False
    else:
        dark.value = None


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

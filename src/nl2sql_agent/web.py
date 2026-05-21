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

from .connection_store import DbConnectionProfile
from .generator import stream_agent_response
from .mcp_bridge import sqlcl_init_config
from .models import UserMessage
from .runtime_connection import reset_runtime_connection, set_runtime_connection


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
.threads-label,
.db-label {
  padding: 10px 10px 6px;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-3);
  font-weight: 600;
}

/* ---------- Database connections (sidebar) ---------- */
.db-section {
  padding: 0 8px 6px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}
.db-list { display: flex; flex-direction: column; gap: 1px; }
.db-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text-2);
  background: transparent;
  border: 0;
  width: 100%;
  text-align: left;
  font-family: inherit;
  cursor: default;
  position: relative;
}
.db-item .db-name {
  flex: 1;
  font-weight: 500;
  color: var(--text);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.db-item.active {
  background: color-mix(in srgb, var(--success) 10%, transparent);
}
.db-item.active .db-name { color: var(--text); }

/* Quasar tooltip override so the host:port/service popup matches the
   token-based theme in both light and dark. */
.q-tooltip {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 8px !important;
  padding: 7px 10px !important;
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
  font-size: 11.5px !important;
  letter-spacing: -0.005em !important;
  box-shadow: var(--shadow-md) !important;
  max-width: 360px !important;
}
.db-status {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-3);
  flex-shrink: 0;
}
.db-item.active .db-status {
  background: var(--success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 22%, transparent);
}
.db-status.active {
  background: var(--success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 22%, transparent);
}
.db-empty {
  padding: 10px 12px;
  font-size: 12.5px;
  color: var(--text-3);
  font-style: italic;
}
.thread-row {
  display: flex;
  align-items: stretch;
  gap: 0;
  margin: 1px 0;
  border-radius: var(--radius-sm);
  position: relative;
  transition: background .12s;
}
.thread-row:hover { background: var(--surface-2); }
.thread-row.active { background: var(--primary-soft); }
.thread-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  color: var(--text-2);
  cursor: pointer;
  font-size: 13.5px;
  border: 0;
  background: transparent;
  text-align: left;
  font-family: inherit;
  min-width: 0;
  transition: color .12s;
}
.thread-row:hover .thread-item { color: var(--text); }
.thread-row.active .thread-item {
  color: var(--primary);
  font-weight: 500;
}
.thread-item .thread-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.thread-item:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent);
}
.thread-del {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px; height: 26px;
  margin: 5px 5px 5px 0;
  border-radius: 6px;
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  opacity: 0;
  transition: opacity .12s, background .12s, color .12s;
  flex-shrink: 0;
}
.thread-row:hover .thread-del,
.thread-row:focus-within .thread-del { opacity: 1; }
.thread-del:hover { background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--danger); }
.thread-del:focus-visible {
  opacity: 1;
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 25%, transparent);
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
_ICON_X = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg>'
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
        if "thread_messages" not in app.storage.user:
            app.storage.user["thread_messages"] = {}
        if "theme" not in app.storage.user:
            app.storage.user["theme"] = "system"
        if "selected_connection" not in app.storage.user:
            app.storage.user["selected_connection"] = ""
        if "thread_connections" not in app.storage.user:
            app.storage.user["thread_connections"] = {}

        # Backfill thread->connection mapping for legacy sessions.
        thread_connections = dict(app.storage.user.get("thread_connections", {}))
        selected_seed = (app.storage.user.get("selected_connection") or "").strip()
        for tid in app.storage.user.get("threads", []):
            thread_connections.setdefault(tid, selected_seed)
        app.storage.user["thread_connections"] = thread_connections

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
                        ui.html('<span class="brand-sub">Oracle • Postgres • Read-only</span>')

                new_chat_btn = ui.element("button").classes("new-chat-btn")
                new_chat_btn.props('type="button" aria-label="Start new conversation"')
                with new_chat_btn:
                    ui.html(_ICON_PLUS)
                    ui.html("<span>New conversation</span>")

                ui.html('<div class="db-label">Database</div>')
                db_section = ui.element("div").classes("db-section")
                with db_section:
                    db_list = ui.element("div").classes("db-list")
                    db_list.props('role="list" aria-label="Database connections"')

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
                    admin_btn = (
                        ui.button("Admin connections")
                        .props('outline dense no-caps aria-label="Open connections admin"')
                        .classes("q-mt-sm full-width")
                    )

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

        def _profile_name(connection_id: str | None) -> str:
            cid = (connection_id or "").strip()
            if not cid:
                return "No connection"
            for conn in getattr(fastapi_state.state, "connection_profiles", []) or []:
                if conn.get("id") == cid:
                    return conn.get("name", cid)
            return cid

        def _get_thread_connection(thread_id: str) -> str:
            mapping = app.storage.user.setdefault("thread_connections", {})
            if thread_id in mapping and mapping[thread_id]:
                return mapping[thread_id]
            fallback = (
                app.storage.user.get("selected_connection")
                or getattr(fastapi_state.state, "active_connection", None)
                or ""
            )
            mapping[thread_id] = fallback
            app.storage.user["thread_connections"] = mapping
            return fallback

        def _set_thread_connection(thread_id: str, connection_id: str) -> None:
            mapping = app.storage.user.setdefault("thread_connections", {})
            mapping[thread_id] = connection_id
            app.storage.user["thread_connections"] = mapping

        def render_threads() -> None:
            threads_container.clear()
            current = app.storage.user.get("current_thread")
            with threads_container:
                for tid in app.storage.user.get("threads", []):
                    row = ui.element("div").classes("thread-row")
                    if tid == current:
                        row.classes(add="active")
                    with row:
                        btn = ui.element("button").classes("thread-item")
                        btn.props(f'type="button" aria-label="Open {_escape(tid)}"')
                        with btn:
                            ui.html(
                                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
                                'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                                'stroke-linejoin="round" aria-hidden="true" style="flex-shrink:0;">'
                                '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
                                '</svg>'
                            )
                            conn_name = _profile_name(_get_thread_connection(tid))
                            ui.html(
                                f'<span class="thread-name">{_escape(tid)}</span>'
                                f'<span class="thread-meta">{_escape(conn_name)}</span>'
                            )
                        btn.on("click", lambda _e, t=tid: switch_thread(t))

                        del_btn = ui.element("button").classes("thread-del")
                        del_btn.props(f'type="button" aria-label="Delete conversation {_escape(tid)}" title="Delete"')
                        with del_btn:
                            ui.html(_ICON_X)
                        del_btn.on("click", lambda _e, t=tid: delete_thread(t))

        conn_render_state = {"active": object(), "names": object()}

        def render_connections(*, force: bool = False) -> None:
            saved = list(getattr(fastapi_state.state, "connection_profiles", []) or [])
            active = getattr(fastapi_state.state, "active_connection", None)
            names_sig = tuple(c.get("id", "") for c in saved)
            if (
                not force
                and conn_render_state["active"] == active
                and conn_render_state["names"] == names_sig
            ):
                return
            conn_render_state["active"] = active
            conn_render_state["names"] = names_sig
            db_list.clear()
            with db_list:
                if not saved:
                    ui.html(
                        '<div class="db-empty">No saved connections. '
                        'Use the Admin button to create one.</div>'
                    )
                    return
                for conn in saved:
                    connection_id = conn.get("id", "")
                    name = conn.get("name", connection_id)
                    db_type = conn.get("db_type", "").strip().lower()
                    target = conn.get("target", "")
                    selected = app.storage.user.get("selected_connection", "") or active or ""
                    is_selected = connection_id == selected
                    is_active = connection_id == active
                    item = ui.element("button").classes("db-item")
                    if is_selected:
                        item.classes(add="active")
                    aria = (
                        f"{name} (selected{' and active' if is_active else ''}) — {target}"
                        if is_selected
                        else f"{name}{' (active)' if is_active else ''} — {target}"
                    )
                    item.props(
                        f'type="button" role="listitem" aria-label="{_escape(aria)}"'
                    )
                    with item:
                        status_class = "db-status" + (" active" if is_active else "")
                        ui.html(f'<span class="{status_class}" aria-hidden="true"></span>')
                        ui.html(
                            f'<span class="db-name">{_escape(name)}'
                            f' <span style="color:var(--text-3);font-weight:400;">'
                            f'[{_escape(db_type or "db")}]</span></span>'
                        )
                    if target:
                        item.tooltip(target)
                    item.on("click", lambda _e, n=connection_id: select_connection(n))

        def select_connection(connection_id: str) -> None:
            app.storage.user["selected_connection"] = connection_id
            current_tid = app.storage.user.get("current_thread", "")
            if current_tid:
                _set_thread_connection(current_tid, connection_id)
            render_connections(force=True)
            render_threads()
            selected = next(
                (
                    c for c in getattr(fastapi_state.state, "connection_profiles", [])
                    if c.get("id") == connection_id
                ),
                None,
            )
            label = selected.get("name", connection_id) if selected else connection_id
            ui.notify(f"Selected connection: {label}", type="info")

        def _slugify(value: str) -> str:
            text = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
            while "--" in text:
                text = text.replace("--", "-")
            return text.strip("-")

        def _reload_profiles(connection_doc) -> None:
            active = getattr(fastapi_state.state, "active_connection", None)
            if not active:
                active = connection_doc.default_connection_id
                fastapi_state.state.active_connection = active
            fastapi_state.state.connection_doc = connection_doc
            fastapi_state.state.connection_profiles = connection_doc.public_profiles(active_id=active)
            fastapi_state.state.sqlcl_connections = connection_doc.sqlcl_connections()
            valid_ids = {p.id for p in connection_doc.profiles}
            mapping = dict(app.storage.user.get("thread_connections", {}))
            fallback = connection_doc.default_connection_id or ""
            for tid in app.storage.user.get("threads", []):
                if mapping.get(tid) not in valid_ids:
                    mapping[tid] = fallback
            app.storage.user["thread_connections"] = mapping
            selected = (app.storage.user.get("selected_connection") or "").strip()
            if selected and selected not in valid_ids:
                app.storage.user["selected_connection"] = fallback
            render_connections(force=True)
            render_threads()

        with ui.dialog() as admin_dialog, ui.card().classes("w-[720px] max-w-[96vw]"):
            ui.label("Connection Admin").classes("text-h6")
            ui.label(
                "Manage Oracle/Postgres profiles stored in a local JSON file."
            ).classes("text-caption")
            admin_state = {"profile_id": ""}
            existing_connections = ui.column().classes("w-full gap-2 q-mt-sm")
            editor_header = ui.label("Add connection").classes("text-subtitle2")
            editor_expansion = ui.expansion("Add / Edit connection", icon="tune").classes("w-full")
            editor_expansion.props("dense")

            with editor_expansion:
                with ui.column().classes("w-full gap-2 q-pt-sm"):
                    with ui.row().classes("w-full items-center gap-2"):
                        profile_name = ui.input("Display name").props("dense outlined").classes("flex-1")
                        db_type = ui.select(
                            options={"oracle": "Oracle", "postgres": "Postgres"},
                            value="oracle",
                            label="Database type",
                        ).props("dense outlined").classes("w-40")

                    oracle_box = ui.column().classes("w-full gap-2")
                    with oracle_box:
                        with ui.row().classes("w-full gap-2"):
                            oracle_host = ui.input("ORACLE_HOST").props("dense outlined").classes("flex-1")
                            oracle_port = ui.number("ORACLE_PORT", value=1521).props("dense outlined").classes("w-40")
                            oracle_service = ui.input("ORACLE_SERVICE_NAME").props("dense outlined").classes("flex-1")
                        with ui.row().classes("w-full gap-2"):
                            oracle_user = ui.input("ORACLE_USER").props("dense outlined").classes("flex-1")
                            oracle_password = ui.input("ORACLE_PASSWORD", password=True, password_toggle_button=True).props("dense outlined").classes("flex-1")
                        with ui.row().classes("w-full gap-2"):
                            oracle_dsn = ui.input("ORACLE_DSN").props("dense outlined").classes("flex-1")

                    postgres_box = ui.column().classes("w-full gap-2")
                    with postgres_box:
                        with ui.row().classes("w-full gap-2"):
                            pg_host = ui.input("POSTGRES_HOST").props("dense outlined").classes("flex-1")
                            pg_port = ui.number("POSTGRES_PORT", value=5432).props("dense outlined").classes("w-40")
                            pg_db = ui.input("POSTGRES_DATABASE").props("dense outlined").classes("flex-1")
                        with ui.row().classes("w-full gap-2"):
                            pg_user = ui.input("POSTGRES_USER").props("dense outlined").classes("flex-1")
                            pg_password = ui.input("POSTGRES_PASSWORD", password=True, password_toggle_button=True).props("dense outlined").classes("flex-1")
                        with ui.row().classes("w-full gap-2"):
                            pg_dsn = ui.input("POSTGRES_DSN").props("dense outlined").classes("flex-1")

                    set_default = ui.checkbox("Set as default profile")

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                btn_new = ui.button("Add connection", color="secondary")
                btn_test = ui.button("Test", color="warning")
                btn_delete = ui.button("Delete", color="negative")
                btn_save = ui.button("Save", color="primary")
                ui.button("Close", on_click=admin_dialog.close)

        with ui.dialog() as new_thread_dialog, ui.card().classes("w-[520px] max-w-[92vw]"):
            ui.label("New conversation").classes("text-h6")
            ui.label("Pick the database connection for this conversation.").classes("text-caption")
            new_thread_connection = ui.select(
                options={},
                label="Database connection",
            ).props("dense outlined")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Cancel", on_click=new_thread_dialog.close)
                btn_create_thread = ui.button("Create conversation", color="primary")

        def _toggle_profile_fields() -> None:
            if db_type.value == "oracle":
                oracle_box.style("display: flex;")
                postgres_box.style("display: none;")
            else:
                oracle_box.style("display: none;")
                postgres_box.style("display: flex;")

        def _fill_form(profile: dict | None) -> None:
            if not profile:
                admin_state["profile_id"] = ""
                editor_header.text = "Add connection"
                editor_header.update()
                profile_name.value = ""
                db_type.value = "oracle"
                oracle_dsn.value = ""
                oracle_host.value = ""
                oracle_port.value = 1521
                oracle_service.value = ""
                oracle_user.value = ""
                oracle_password.value = ""
                pg_dsn.value = ""
                pg_host.value = ""
                pg_port.value = 5432
                pg_db.value = ""
                pg_user.value = ""
                pg_password.value = ""
                set_default.value = False
                _toggle_profile_fields()
                return

            admin_state["profile_id"] = profile.get("id", "")
            editor_header.text = f"Editing: {profile.get('name', profile.get('id', 'connection'))}"
            editor_header.update()
            profile_name.value = profile.get("name", "")
            db_type.value = profile.get("db_type", "oracle")
            oracle_dsn.value = profile.get("oracle_dsn", "")
            oracle_host.value = profile.get("oracle_host", "")
            oracle_port.value = profile.get("oracle_port", 1521)
            oracle_service.value = profile.get("oracle_service_name", "")
            oracle_user.value = profile.get("oracle_user", "")
            oracle_password.value = profile.get("oracle_password", "")
            pg_dsn.value = profile.get("postgres_dsn", "")
            pg_host.value = profile.get("postgres_host", "")
            pg_port.value = profile.get("postgres_port", 5432)
            pg_db.value = profile.get("postgres_database", "")
            pg_user.value = profile.get("postgres_user", "")
            pg_password.value = profile.get("postgres_password", "")
            doc = getattr(fastapi_state.state, "connection_doc", None)
            set_default.value = bool(doc and doc.default_connection_id == profile.get("id"))
            _toggle_profile_fields()

        def _profile_map() -> dict[str, dict]:
            doc = getattr(fastapi_state.state, "connection_doc", None)
            if doc is None:
                return {}
            return {p.id: p.model_dump(mode="json") for p in doc.profiles}

        def _test_profile(profile: DbConnectionProfile) -> tuple[bool, str]:
            try:
                if profile.db_type == "oracle":
                    import oracledb

                    connection = oracledb.connect(
                        user=profile.oracle_user.strip(),
                        password=profile.oracle_password.strip(),
                        dsn=profile.oracle_dsn.strip() or profile.oracle_target(),
                    )
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT 1 FROM DUAL")
                            cursor.fetchone()
                    finally:
                        connection.close()
                else:
                    import psycopg

                    if profile.postgres_dsn.strip():
                        connection = psycopg.connect(profile.postgres_dsn.strip())
                    else:
                        connection = psycopg.connect(
                            host=profile.postgres_host.strip(),
                            port=profile.postgres_port,
                            dbname=profile.postgres_database.strip(),
                            user=profile.postgres_user.strip(),
                            password=profile.postgres_password.strip(),
                        )
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT 1")
                            cursor.fetchone()
                    finally:
                        connection.close()
            except Exception as exc:
                return False, str(exc)

            return True, "Connection successful."

        def _refresh_admin_report() -> None:
            doc = getattr(fastapi_state.state, "connection_doc", None)
            existing_connections.clear()
            if doc is None or not doc.profiles:
                with existing_connections:
                    ui.label("Existing connections").classes("text-subtitle2")
                    ui.label("No connections yet. Use Add connection to create one.").classes(
                        "text-caption text-grey-6"
                    )
                return

            with existing_connections:
                ui.label("Existing connections").classes("text-subtitle2")
                for p in doc.profiles:
                    with ui.card().classes("w-full q-pa-sm"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.column().classes("gap-0"):
                                default_mark = " (default)" if doc.default_connection_id == p.id else ""
                                ui.label(f"{p.name}{default_mark}").classes("text-weight-medium")
                                ui.label(f"{p.db_type.upper()} - {p.target_display()}").classes(
                                    "text-caption text-grey-6"
                                )
                            with ui.row().classes("items-center gap-2"):
                                ui.button(
                                    "Edit",
                                    on_click=lambda _e, pid=p.id: _edit_profile(pid),
                                ).props("flat dense")
                                ui.button(
                                    "Test",
                                    on_click=lambda _e, pid=p.id: _test_existing_profile(pid),
                                ).props("flat dense")

        def _open_admin() -> None:
            _refresh_admin_report()
            _fill_form(None)
            editor_expansion.value = False
            admin_dialog.open()

        def _edit_profile(profile_id: str) -> None:
            by_id = _profile_map()
            profile = by_id.get(profile_id)
            if profile is None:
                ui.notify("Connection not found.", type="warning")
                return
            _fill_form(profile)
            editor_expansion.value = True

        def _test_existing_profile(profile_id: str) -> None:
            by_id = _profile_map()
            data = by_id.get(profile_id)
            if data is None:
                ui.notify("Connection not found.", type="warning")
                return
            try:
                profile = DbConnectionProfile.model_validate(data)
            except Exception as exc:
                ui.notify(f"Invalid profile: {exc}", type="negative", multi_line=True)
                return
            ok, message = _test_profile(profile)
            if ok:
                ui.notify(f"{profile.name}: {message}", type="positive")
            else:
                ui.notify(f"{profile.name}: {message}", type="negative", multi_line=True)

        def _save_profile() -> None:
            store = getattr(fastapi_state.state, "connection_store", None)
            if store is None:
                ui.notify("Connection store is unavailable.", type="negative")
                return

            connection_id = (admin_state.get("profile_id") or "").strip()
            if not connection_id:
                connection_id = _slugify(profile_name.value or "") or _slugify(db_type.value or "db")
            profile_data = {
                "id": connection_id,
                "name": (profile_name.value or "").strip() or connection_id,
                "db_type": db_type.value,
                "oracle_dsn": (oracle_dsn.value or "").strip(),
                "oracle_host": (oracle_host.value or "").strip(),
                "oracle_port": int(oracle_port.value or 1521),
                "oracle_service_name": (oracle_service.value or "").strip(),
                "oracle_user": (oracle_user.value or "").strip(),
                "oracle_password": (oracle_password.value or "").strip(),
                "postgres_dsn": (pg_dsn.value or "").strip(),
                "postgres_host": (pg_host.value or "").strip(),
                "postgres_port": int(pg_port.value or 5432),
                "postgres_database": (pg_db.value or "").strip(),
                "postgres_user": (pg_user.value or "").strip(),
                "postgres_password": (pg_password.value or "").strip(),
            }
            try:
                profile = DbConnectionProfile.model_validate(profile_data)
            except Exception as exc:
                ui.notify(f"Invalid profile: {exc}", type="negative", multi_line=True)
                return

            new_doc = store.upsert(profile, set_default=bool(set_default.value))
            fastapi_state.state.active_connection = (
                fastapi_state.state.active_connection or new_doc.default_connection_id
            )
            _reload_profiles(new_doc)

            # Keep SQLcl wallet updated immediately for newly saved Oracle profiles.
            settings = getattr(fastapi_state.state, "settings", None)
            if (
                settings
                and profile.db_type == "oracle"
                and getattr(settings, "sqlcl_path", "")
            ):
                conn_string = profile.to_sqlcl_connection_string()
                if conn_string:
                    try:
                        sqlcl_init_config(
                            settings.sqlcl_path,
                            profile.id,
                            conn_string,
                            sqlcl_user_dir=settings.sqlcl_user_dir or None,
                        )
                    except Exception as exc:
                        ui.notify(f"Saved but SQLcl wallet update failed: {exc}", type="warning")

            admin_state["profile_id"] = profile.id
            _refresh_admin_report()
            editor_expansion.value = False
            ui.notify(f"Saved profile: {profile.name}", type="positive")

        def _test_form_profile() -> None:
            profile_data = {
                "id": (admin_state.get("profile_id") or "temp-test").strip() or "temp-test",
                "name": (profile_name.value or "").strip() or "Test connection",
                "db_type": db_type.value,
                "oracle_dsn": (oracle_dsn.value or "").strip(),
                "oracle_host": (oracle_host.value or "").strip(),
                "oracle_port": int(oracle_port.value or 1521),
                "oracle_service_name": (oracle_service.value or "").strip(),
                "oracle_user": (oracle_user.value or "").strip(),
                "oracle_password": (oracle_password.value or "").strip(),
                "postgres_dsn": (pg_dsn.value or "").strip(),
                "postgres_host": (pg_host.value or "").strip(),
                "postgres_port": int(pg_port.value or 5432),
                "postgres_database": (pg_db.value or "").strip(),
                "postgres_user": (pg_user.value or "").strip(),
                "postgres_password": (pg_password.value or "").strip(),
            }
            try:
                profile = DbConnectionProfile.model_validate(profile_data)
            except Exception as exc:
                ui.notify(f"Invalid profile: {exc}", type="negative", multi_line=True)
                return
            ok, message = _test_profile(profile)
            if ok:
                ui.notify(message, type="positive")
            else:
                ui.notify(message, type="negative", multi_line=True)

        def _delete_profile() -> None:
            store = getattr(fastapi_state.state, "connection_store", None)
            if store is None:
                return
            connection_id = (admin_state.get("profile_id") or "").strip()
            if not connection_id:
                ui.notify("Pick a profile to delete.", type="warning")
                return
            new_doc = store.delete(connection_id)
            if app.storage.user.get("selected_connection") == connection_id:
                app.storage.user["selected_connection"] = new_doc.default_connection_id or ""
            if getattr(fastapi_state.state, "active_connection", None) == connection_id:
                fastapi_state.state.active_connection = new_doc.default_connection_id
            _reload_profiles(new_doc)
            _fill_form(None)
            _refresh_admin_report()
            ui.notify(f"Deleted profile: {connection_id}", type="info")

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

        def _get_transcript(tid: str) -> list[dict]:
            messages = app.storage.user.setdefault("thread_messages", {})
            return messages.setdefault(tid, [])

        def _save_transcript(tid: str, transcript: list[dict]) -> None:
            messages = app.storage.user.setdefault("thread_messages", {})
            messages[tid] = transcript
            app.storage.user["thread_messages"] = messages

        def _render_user_bubble(text: str) -> None:
            with chat_box:
                with ui.element("div").classes("msg user"):
                    with ui.element("div").classes("bubble"):
                        ui.html(f"<span>{_escape(text)}</span>")

        def _render_bot_bubble(markdown_text: str) -> None:
            with chat_box:
                with ui.element("div").classes("msg bot"):
                    with ui.element("div").classes("bubble"):
                        ui.markdown(markdown_text)

        def render_chat_history() -> None:
            chat_box.clear()
            tid = app.storage.user.get("current_thread", "")
            transcript = _get_transcript(tid)
            if not transcript:
                show_empty(True)
                return
            show_empty(False)
            for entry in transcript:
                role = entry.get("role")
                content = entry.get("content", "")
                if role == "user":
                    _render_user_bubble(content)
                else:
                    _render_bot_bubble(content)
            scroll_area.scroll_to(percent=1.0)

        def _connection_options() -> dict[str, str]:
            options: dict[str, str] = {}
            for conn in getattr(fastapi_state.state, "connection_profiles", []) or []:
                cid = conn.get("id", "")
                if not cid:
                    continue
                options[cid] = f"{conn.get('name', cid)} [{conn.get('db_type', 'db')}]"
            return options

        def _open_new_thread_picker() -> None:
            options = _connection_options()
            if not options:
                ui.notify("Create a database connection first in Admin connections.", type="warning")
                return
            new_thread_connection.options = options
            current_tid = app.storage.user.get("current_thread", "")
            current_conn = _get_thread_connection(current_tid)
            if current_conn in options:
                new_thread_connection.value = current_conn
            else:
                new_thread_connection.value = app.storage.user.get("selected_connection") or next(iter(options))
            new_thread_dialog.open()

        async def create_new_thread(connection_id: str) -> None:
            chosen_connection = (connection_id or "").strip()
            if not chosen_connection:
                ui.notify("Pick a database connection to continue.", type="warning")
                return
            new_id = f"Session {uuid.uuid4().hex[:4].upper()}"
            app.storage.user["threads"].append(new_id)
            app.storage.user["current_thread"] = new_id
            _set_thread_connection(new_id, chosen_connection)
            app.storage.user["selected_connection"] = chosen_connection
            _save_transcript(new_id, [])
            render_threads()
            render_connections(force=True)
            render_chat_history()
            new_thread_dialog.close()
            ui.notify(f"New session: {new_id}", type="positive")

        def switch_thread(new_thread_id: str) -> None:
            app.storage.user["current_thread"] = new_thread_id
            app.storage.user["selected_connection"] = _get_thread_connection(new_thread_id)
            render_threads()
            render_connections(force=True)
            render_chat_history()
            close_drawer()

        def delete_thread(tid: str) -> None:
            threads = list(app.storage.user.get("threads", []))
            if tid not in threads:
                return
            threads.remove(tid)
            messages = app.storage.user.setdefault("thread_messages", {})
            messages.pop(tid, None)
            thread_connections = app.storage.user.setdefault("thread_connections", {})
            thread_connections.pop(tid, None)
            app.storage.user["threads"] = threads
            app.storage.user["thread_messages"] = messages
            app.storage.user["thread_connections"] = thread_connections

            current = app.storage.user.get("current_thread")
            if not threads:
                # Last conversation removed — recreate the default so the UI
                # always has a thread to land on.
                threads.append(_DEFAULT_THREAD)
                app.storage.user["threads"] = threads
                app.storage.user["current_thread"] = _DEFAULT_THREAD
                _save_transcript(_DEFAULT_THREAD, [])
                _set_thread_connection(_DEFAULT_THREAD, app.storage.user.get("selected_connection") or "")
            elif current == tid:
                app.storage.user["current_thread"] = threads[0]
            app.storage.user["selected_connection"] = _get_thread_connection(
                app.storage.user["current_thread"]
            )

            render_threads()
            render_chat_history()
            ui.notify(f'Deleted "{tid}"', type="info")

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

            send_thread_id = app.storage.user["current_thread"]
            transcript = _get_transcript(send_thread_id)
            transcript.append({"role": "user", "content": texto})
            _save_transcript(send_thread_id, transcript)

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

            runtime_token = None
            try:
                # Lazy import to avoid a circular import at module load time
                # (main.py imports web.init_nicegui inside _maybe_mount_nicegui).
                from .main import activate_request_connection

                usuario_obj = UserMessage(
                    message=texto,
                    user_id=app.storage.user["user_id"],
                    thread_id=app.storage.user["current_thread"],
                    connection_id=_get_thread_connection(app.storage.user["current_thread"]) or None,
                )

                chosen_profile = await activate_request_connection(fastapi_state, usuario_obj)
                runtime_token = set_runtime_connection(chosen_profile)

                tool_state = {"name": None, "count": 1}

                async for chunk_str in stream_agent_response(
                    fastapi_state.state.agent, usuario_obj, chosen_profile
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
                if runtime_token is not None:
                    reset_runtime_connection(runtime_token)
                if thinking_el is not None:
                    thinking_el.style("display: none;")
                if not full_response and response_md is not None:
                    bubble_el.style("display: block;")
                    response_md.set_content(
                        "_(no textual response — check the server logs "
                        "for the agent's last message)_"
                    )
                if full_response:
                    transcript.append({"role": "bot", "content": full_response})
                    _save_transcript(send_thread_id, transcript)
                local_state["is_processing"] = False
                msg_input.enable()
                send_btn.props(remove="disabled")
                msg_input.run_method("focus")
                scroll_area.scroll_to(percent=1.0)

        # ----- wire events -----
        new_chat_btn.on("click", lambda _e: _open_new_thread_picker())
        hamburger.on("click", lambda _e: open_drawer())
        scrim.on("click", lambda _e: close_drawer())
        btn_light.on("click", lambda _e: set_theme("light"))
        btn_auto.on("click", lambda _e: set_theme("system"))
        btn_dark.on("click", lambda _e: set_theme("dark"))
        admin_btn.on("click", lambda _e: _open_admin())
        db_type.on("update:model-value", lambda _e: _toggle_profile_fields())
        btn_new.on(
            "click",
            lambda _e: (_fill_form(None), setattr(editor_expansion, "value", True)),
        )
        btn_test.on("click", lambda _e: _test_form_profile())
        btn_save.on("click", lambda _e: _save_profile())
        btn_delete.on("click", lambda _e: _delete_profile())
        btn_create_thread.on("click", lambda _e: create_new_thread(new_thread_connection.value or ""))
        send_btn.on("click", lambda _e: send())
        msg_input.on("keydown.enter.exact.prevent", send)

        # ----- initial render -----
        render_connections(force=True)
        current_tid = app.storage.user.get("current_thread", _DEFAULT_THREAD)
        selected_for_thread = _get_thread_connection(current_tid)
        if not selected_for_thread:
            selected_for_thread = getattr(fastapi_state.state, "active_connection", None) or ""
            _set_thread_connection(current_tid, selected_for_thread)
        app.storage.user["selected_connection"] = selected_for_thread
        render_connections(force=True)
        render_threads()
        render_suggestions()
        render_chat_history()
        update_theme_seg()
        _toggle_profile_fields()

        # Poll the active connection so the green dot follows the agent
        # whenever it switches MCP `connect` mid-conversation. Cheap when
        # nothing changed (the helper short-circuits before touching DOM).
        ui.timer(3.0, render_connections)


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

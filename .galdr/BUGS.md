# BUGS

## Open Bugs
No bugs logged.

## Closed Bugs

### BUG-001
- **Title**: GUI swallows stream errors — spinner never stops, user sees nothing
- **Severity**: High
- **Status**: Fixed
- **File**: src/nl2sql_agent/web.py, src/nl2sql_agent/generator.py
- **Root cause**: `web.py` only branched on `type == "tool"` and `type == "text"`; `type == "error"` chunks were silently dropped, leaving the "Calling: …" spinner visible.
- **Fix**:
  - `generator.py`: catch `openai.BadRequestError` separately, extract `body.error.message` for a friendly summary, emit `{type:"error", kind:"bad_request", content:friendly, detail:str(exc)}`.
  - `web.py`: added `elif data.get("type") == "error":` branch that hides the tool spinner, logs the detail to loguru AND the browser dev console (`ui.run_javascript("console.error(...)")`), renders a `⚠️` line in the chat, fires `ui.notify(... type="negative")`, and breaks out of the stream.
- **Created**: 2026-04-29
- **Closed**: 2026-04-29

---
id: 2
title: Remove `/ask` legacy path; keep only `/gui` + `/api/v1/chat-stream`
status: completed
type: refactor
subsystems: [core-engine, automation-scripts, test-suite]
dependencies: [1]
created: 2026-04-29
completed: 2026-04-29
---

# TASK-002 — Drop `/ask` legacy path

## Goal
Cleanup the repo to keep only the features relevant for the NiceGUI at `/gui` and the streaming chat webservice at `/api/v1/chat-stream/`. Drop the standalone direct-OpenAI `/ask` flow and its rate-limit settings/tests.

## Changes

### Tier 1 — core cleanup
- Deleted `src/nl2sql_agent/llm.py` (`SqlGenerator`).
- Deleted `tests/test_llm.py`.
- Deleted 5 `docs/20260428_093815_Cursor_ASK_TEST_*.md` files.
- Removed `/ask` route, `AskRequest`, `AskResponse`, `app.state.sql_generator`, `app.state.schema_ctx`, `verify_question_objects_against_catalog` call, and all `SqlGenerator` imports from `src/nl2sql_agent/main.py`.
- Rewrote `README.md` to remove `/ask` framing.

### Tier 2 — polish
- Removed dead helpers: `executor.classify_oracle_error`, `executor.is_safe_retry_class`, `oracle_catalog.verify_question_objects_against_catalog`, `oracle_catalog.unknown_schema_tokens`, `oracle_catalog.friendly_missing_source_message`, `oracle_catalog._has_similar_known_name`, `oracle_catalog._normalized_name`, `oracle_catalog._SQL_RESERVED`, `oracle_catalog._question_identifier_tokens`.
- Removed non-streaming `/api/v1/chat/` endpoint and `generator.agent_response()` (the GUI never used the blocking variant).
- Renamed `ask_rate_limit_*` settings → `chat_rate_limit_*` in `settings.py`, `main.py`, and `.env.example`.
- Removed obsolete settings: `schema_retrieval_enabled`, `sql_repair_enabled`, `sql_repair_max_attempts`.
- Trimmed `tests/test_executor_guard.py` and `tests/test_oracle_catalog.py` to only test still-living code.
- Updated `tests/test_settings.py` for renamed settings.

## Verification
- `uv run pytest -q` → **34 passed in 4.04s**.
- `uv run python -c "from nl2sql_agent import main; ..."` → routes are exactly `['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc', '/health', '/api/v1/chat-stream/', '/gui']`.
- No orphan references to removed symbols.

## Out of scope (left for future tasks)
- Force-rerunning end-to-end through `/gui` against a live Oracle DB (requires lab env).
- Adding `scripts/install-instantclient.{ps1,sh}` to mirror the SQLcl install pattern.
- Switching to `python-oracledb` thin mode by default to drop the `third_party/instantclient_23_0/` dependency entirely.

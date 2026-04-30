# NL2SQL Agent — Implementation TODO (Swarm-Ready)

Source: `docs/20260425_002553_Claude_NL2SQL_AGENT_DESIGN.md`

This checklist is organized for `@g-go-code-swarm` execution with conflict-safe buckets.

## Swarm execution order

- Phase 1 (can run in parallel): Buckets A, B
- Phase 2 (can run in parallel): Buckets C, D, E
- Phase 3 (depends on C, D, E): Bucket F
- Phase 4: Bucket G

---

## Bucket A - Project scaffolding and dependencies

Owner files:
- `pyproject.toml`
- `requirements.txt`
- `.gitignore`
- `.env.example`
- `src/nl2sql_agent/__init__.py`

Tasks:
- [ ] Define uv-managed package in `pyproject.toml`
- [ ] Add runtime deps: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `openai`, `oracledb`
- [ ] Add test deps: `pytest`
- [ ] Sync pinned dependencies into `requirements.txt`
- [ ] Add ignore rules for `.venv`, `.env`, `data/schema.json`, caches
- [ ] Add required env vars to `.env.example`

Acceptance:
- [ ] `uv pip install -r requirements.txt` succeeds
- [ ] `python -c "import nl2sql_agent"` works from project venv

## Bucket B - Oracle schema export

Owner files:
- `scripts/export_schema.sql`

Tasks:
- [ ] Build SQLcl export script for tables, columns, views, synonyms, PK/FK constraints
- [ ] Emit one valid JSON document with stable keys

Acceptance:
- [ ] `sql -name WCU_C1002 @scripts/export_schema.sql > data/schema.json` creates non-empty file
- [ ] `data/schema.json` parses as JSON

## Bucket C - Settings and schema context

Owner files:
- `src/nl2sql_agent/settings.py`
- `src/nl2sql_agent/schema_loader.py`
- `tests/test_schema_loader.py`

Tasks:
- [ ] Implement `BaseSettings` in `settings.py` with all v1 fields from design
- [ ] Implement `load_schema(path) -> SchemaContext`
- [ ] Implement `SchemaContext.as_prompt()` with char-budget truncation
- [ ] Add schema loader unit tests with fixture-based assertions

Acceptance:
- [ ] Missing schema path raises clear error
- [ ] Prompt output includes table/column and FK relation format
- [ ] `pytest tests/test_schema_loader.py` passes

## Bucket D - LLM SQL generation

Owner files:
- `src/nl2sql_agent/llm.py`
- `tests/test_llm.py`

Tasks:
- [ ] Implement `generate_sql(question, ctx)` using OpenAI client
- [ ] Enforce strict Oracle read-only system prompt
- [ ] Strip code fences and normalize model output to raw SQL
- [ ] Add unit tests with mocked OpenAI response

Acceptance:
- [ ] Output is a single SQL statement string
- [ ] Fence stripping works for ```sql wrappers
- [ ] `pytest tests/test_llm.py` passes

## Bucket E - Query execution and safety guard

Owner files:
- `src/nl2sql_agent/executor.py`
- `tests/test_executor_guard.py`

Tasks:
- [ ] Implement SELECT/WITH-only validator (reject DML/DDL/procedural/statement chaining)
- [ ] Implement Oracle execution with thin mode and read-only credentials
- [ ] Apply `cursor.callTimeout` from settings
- [ ] Enforce row cap even when SQL has no `FETCH FIRST`
- [ ] Return `{columns, rows, row_count, elapsed_ms}`
- [ ] Add guard unit tests for accepted and rejected patterns

Acceptance:
- [ ] Rejected SQL returns deterministic error path
- [ ] `pytest tests/test_executor_guard.py` passes

## Bucket F - FastAPI orchestration

Owner files:
- `src/nl2sql_agent/main.py`

Tasks:
- [ ] Implement app startup to cache schema context
- [ ] Add `GET /health` returning `{"status":"ok"}`
- [ ] Add `POST /ask` request/response models
- [ ] Wire flow: question -> `generate_sql` -> `run_select` -> response payload
- [ ] Map failures to expected HTTP statuses from design doc

Acceptance:
- [ ] App boots with valid env and schema
- [ ] `/health` returns 200
- [ ] `/ask` returns SQL + rows structure on valid input

## Bucket G - End-to-end verification and docs

Owner files:
- `README.md`

Tasks:
- [ ] Document full setup flow (uv venv, install, env, schema export, run)
- [ ] Run full test suite and record command outputs
- [ ] Manual smoke test: `/health`
- [ ] Manual smoke test: `/ask` with "list 5 tables"
- [ ] Manual domain query and compare with hand-written SQL result

Acceptance:
- [ ] `pytest` all green
- [ ] Uvicorn launch command works
- [ ] README reflects validated commands only

---

## Deferred (v2 backlog)

- [ ] ORDS PL/SQL proxy in `obs/english/database/packages/`
- [ ] Authentication (basic auth or JWT)
- [ ] Audit log storage per `/ask` call
- [ ] Multi-connection support
- [ ] Schema refresh automation
- [ ] SQLcl MCP integration in execution path
- [ ] Anthropic provider support

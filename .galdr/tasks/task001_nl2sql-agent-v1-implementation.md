---
id: 1
title: 'Implement NL2SQL Agent v1'
status: awaiting-verification
priority: high
subsystems: [core-engine, data-assets, automation-scripts, test-suite]
project_context: 'Deliver end-to-end NL2SQL Agent v1 from schema export through FastAPI ask flow based on approved design and TODO docs.'
dependencies: []
blast_radius: medium
requires_verification: true
ai_safe: true
spec_version: "1.0"
execution_cost: high
---

# Task 001 - Implement NL2SQL Agent v1

## Objective
Build the NL2SQL Agent v1 exactly as specified in:
- `docs/20260425_002553_Claude_NL2SQL_AGENT_DESIGN.md`
- `docs/20260425_002553_Claude_NL2SQL_AGENT_TODO.md`

## Scope Boundaries
- In scope: implementation and verification for TODO buckets A-G.
- Out of scope (deferred): v2 backlog items listed in the TODO/design docs.

## Acceptance Criteria (Mapped to Buckets A-G)

### A. Project scaffolding and dependencies
- `pyproject.toml` defines UV-managed package for `nl2sql_agent`.
- Runtime dependencies include `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `openai`, `oracledb`.
- Test dependency includes `pytest`.
- `requirements.txt` is synchronized to the declared dependencies.
- `.gitignore` includes `.venv`, `.env`, `data/schema.json`, and common caches.
- `.env.example` includes required runtime variables.
- Verification:
  - `uv pip install -r requirements.txt` succeeds.
  - `python -c "import nl2sql_agent"` works in project venv.

### B. Oracle schema export
- `scripts/export_schema.sql` exports tables, columns, views, synonyms, PK/FK constraints.
- Output is a single valid JSON document with stable keys.
- Verification:
  - `sql -name WCU_C1002 @scripts/export_schema.sql > data/schema.json` generates non-empty output.
  - `data/schema.json` parses as valid JSON.

### C. Settings and schema context
- `settings.py` defines all v1 settings via `BaseSettings`.
- `schema_loader.py` implements `load_schema(path) -> SchemaContext`.
- `SchemaContext.as_prompt()` renders schema context with bounded/truncated prompt budget.
- Unit tests added for schema loading and prompt rendering.
- Verification:
  - Missing schema file path raises clear error.
  - Prompt contains table/column and FK relationship representation.
  - `pytest tests/test_schema_loader.py` passes.

### D. LLM SQL generation
- `llm.py` implements `generate_sql(question, ctx)` using OpenAI client.
- Oracle read-only single-statement system prompt is enforced.
- Markdown code fences are stripped from model output when present.
- Unit tests mock OpenAI responses and validate output normalization.
- Verification:
  - Output is exactly one SQL statement string.
  - Fence stripping handles ```sql wrappers.
  - `pytest tests/test_llm.py` passes.

### E. Query execution and safety guard
- `executor.py` enforces SELECT/WITH-only policy and rejects DML/DDL/procedural/chained SQL.
- Oracle execution uses read-only credentials in thin mode.
- `cursor.callTimeout` is applied from settings.
- Row cap is enforced even when SQL omits FETCH limit.
- Result payload includes `{columns, rows, row_count, elapsed_ms}`.
- Guard tests cover accepted and rejected query patterns.
- Verification:
  - Rejected SQL returns deterministic error path.
  - `pytest tests/test_executor_guard.py` passes.

### F. FastAPI orchestration
- `main.py` caches schema context at startup.
- `GET /health` returns `{"status":"ok"}`.
- `POST /ask` request/response models are implemented.
- End-to-end flow is wired: question -> SQL generation -> guarded execution -> response payload.
- Failures map to documented HTTP status and error contracts.
- Verification:
  - App boots with valid env and schema.
  - `/health` returns HTTP 200.
  - `/ask` returns SQL plus rows payload on valid input.

### G. End-to-end verification and docs
- `README.md` documents validated setup/run flow.
- Full test suite executed and results captured.
- Manual smoke tests executed for `/health` and `/ask`.
- At least one domain query is validated against equivalent hand-written SQL result.
- Verification:
  - `pytest` is green.
  - Uvicorn launch command works.
  - README reflects only validated commands.

## Acceptance Criteria Progress (A-G)
- [x] **A** Project scaffolding and dependencies implemented.
- [x] **B** Oracle schema export implemented with JSON output contract.
- [x] **C** Settings and schema context implemented with loader coverage.
- [x] **D** LLM SQL generation implemented with normalization and guards.
- [x] **E** Query execution safety guard implemented with rejection coverage.
- [x] **F** FastAPI orchestration (`/health`, `/ask`) implemented end-to-end.
- [x] **G** End-to-end validation/docs updated and test suite reported green.

## Status History
| Timestamp (UTC) | From | To | By | Notes |
|---|---|---|---|---|
| 2026-04-25 03:49 | pending | in-progress | galdr-task-manager | Task created and started from design + TODO specs. |
| 2026-04-25 03:54 | in-progress | in-progress | implementer | Buckets A-G implementation completed; evidence captured with targeted guard/loader/LLM tests and full `pytest` run passing. |
| 2026-04-25 03:54 | in-progress | awaiting-verification | galdr-task-manager | Lifecycle advanced post-implementation; awaiting independent verification for acceptance evidence and manual API smoke confirmation. |
| 2026-04-25 03:57 | awaiting-verification | in-progress | galdr-task-manager | Reopened for requested enhancement: apply OCI thick mode configuration support via Instant Client/Oracle Client. |
| 2026-04-25 04:00 | in-progress | awaiting-verification | galdr-task-manager | OCI thick mode support implemented and tests passed (`uv run pytest`). |
| 2026-04-25 04:24 | awaiting-verification | in-progress | galdr-task-manager | Reopened for follow-up fix: schema loader compatibility for SQLcl schema output encoding (UTF-16/UTF-8). |
| 2026-04-25 04:28 | in-progress | awaiting-verification | galdr-task-manager | Added UTF-16 schema decode support, fixed export SQL syntax, and improved invalid JSON guidance for clearer recovery steps. |

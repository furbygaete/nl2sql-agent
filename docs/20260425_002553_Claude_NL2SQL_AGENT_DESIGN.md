# NL2SQL Agent — v1 Design

## Context

Service where an HTTP client POSTs a plain-English question and gets back SQL + query results from the Oracle database. Original framing — "web requests against an MCP like sqlcl" — resolved into a Natural-Language-to-SQL pipeline:

1. **SQLcl** exports the schema (tables, views, synonyms, FK relationships) to a JSON file once.
2. A **Python FastAPI agent** loads that JSON, sends each user question to **OpenAI** with the schema as context, gets back a `SELECT` statement, executes it via **python-oracledb**, and returns SQL + rows as JSON.
3. ORDS PL/SQL proxy is **deferred to v2** — v1 is localhost-only with no auth, so ORDS in front adds work without value yet.

Intended outcome: a small standalone project the user can run locally, ask "list employees hired in 2025", and get rows back. Proves the loop end-to-end so later phases (auth, ORDS proxy, multi-DB, audit logging, MCP fidelity) can be layered on confidently.

## Architecture

```
┌─────────────┐      ┌──────────────────────────┐      ┌───────────┐
│ HTTP client │ ───▶ │ FastAPI agent (Python)   │ ───▶ │ Oracle DB │
│ (curl, etc) │      │  - loads schema.json     │      │  (26ai)   │
└─────────────┘      │  - calls OpenAI for SQL  │ ◀─── └───────────┘
                     │  - runs SQL via          │
                     │    python-oracledb       │
                     └──────────────────────────┘
                              ▲
                              │ schema.json (one-time)
                     ┌──────────────────────────┐
                     │ SQLcl export script      │
                     │  scripts/export_schema   │
                     └──────────────────────────┘
```

## Project location

Standalone repo at `C:\Users\fdpg8\GitLab\new\nl2sql-agent\`.

## Final structure

```
nl2sql-agent/
├── pyproject.toml                  # uv-managed
├── requirements.txt                # kept in sync with pyproject.toml
├── .env.example                    # OPENAI_API_KEY, ORACLE_DSN, ORACLE_RO_USER/PASSWORD
├── .gitignore                      # .venv, .env, data/schema.json
├── README.md                       # setup + run instructions
├── scripts/
│   └── export_schema.sql           # SQLcl script → JSON on stdout
├── data/
│   └── schema.json                 # generated, gitignored
├── tests/
│   ├── test_executor_guard.py
│   ├── test_schema_loader.py
│   └── test_llm.py
└── src/nl2sql_agent/
    ├── __init__.py
    ├── main.py                     # FastAPI app, POST /ask, GET /health
    ├── schema_loader.py            # load + flatten schema.json
    ├── llm.py                      # OpenAI client, NL → SQL
    ├── executor.py                 # python-oracledb runner + SELECT guard
    └── settings.py                 # pydantic-settings reads .env
```

## Components

### `scripts/export_schema.sql` (SQLcl)
- Queries `USER_TABLES`, `USER_TAB_COLUMNS`, `USER_VIEWS`, `USER_SYNONYMS`, `USER_CONSTRAINTS` (types `R`/`P`), `USER_CONS_COLUMNS`.
- Emits one JSON document using native `JSON_OBJECT` / `JSON_ARRAYAGG`.
- Invocation: `sql -name WCU_C1002 @scripts/export_schema.sql > data/schema.json`.
- Re-run manually when schema changes — agent must restart to pick up updates.

### `src/nl2sql_agent/settings.py`
- `pydantic-settings` `BaseSettings` → loads `.env`.
- Fields: `openai_api_key`, `openai_model` (default `gpt-4o`), `oracle_dsn`, `oracle_ro_user`, `oracle_ro_password`, `schema_path` (default `data/schema.json`), `max_rows` (default `1000`), `query_timeout_s` (default `30`), `host` (default `127.0.0.1`), `port` (default `8000`).

### `src/nl2sql_agent/schema_loader.py`
- `load_schema(path) -> SchemaContext` — reads JSON, raises if missing.
- `SchemaContext.as_prompt() -> str` — compact text view: `TABLE foo (col1 TYPE, col2 TYPE) FK col1 -> bar.id`. Truncates to a max char budget so prompt stays bounded.

### `src/nl2sql_agent/llm.py`
- `generate_sql(question: str, ctx: SchemaContext) -> str`.
- System prompt: "You are an Oracle SQL generator. Output ONE read-only SELECT statement and nothing else, no markdown, no commentary. Use only tables/columns shown in the schema. Add `FETCH FIRST {max_rows} ROWS ONLY` if the user does not specify a limit."
- Strips ```` ```sql ```` fences if model adds them anyway.

### `src/nl2sql_agent/executor.py`
- `run_select(sql: str) -> dict` returning `{columns, rows, row_count, elapsed_ms}`.
- Guard: after upper-case + strip, must start with `SELECT` or `WITH`; reject `;` chains, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`, `ALTER`, `TRUNCATE`, `BEGIN`, `CALL`, `EXEC`.
- Connects via `python-oracledb` thin mode using **read-only DB user** (`oracle_ro_user`).
- Sets `cursor.callTimeout = query_timeout_s * 1000` and `cursor.arraysize = 200`.
- Caps rows at `max_rows` even if SQL omitted the FETCH clause.

### `src/nl2sql_agent/main.py`
- FastAPI app, single dependency: cached `SchemaContext` loaded at startup.
- `POST /ask` — body `AskRequest{question: str}` → response `AskResponse{sql, columns, rows, row_count, elapsed_ms}`.
- `GET /health` → `{"status": "ok"}`.
- Bound to `127.0.0.1:8000` (localhost-only, no auth).

## Data flow — one request

1. Client `POST /ask` with `{"question": "How many active employees were hired in 2025?"}`
2. `main.py` validates body, calls `llm.generate_sql(question, schema_context)`
3. OpenAI returns: `SELECT COUNT(*) FROM employees WHERE active_flag='Y' AND hire_date >= DATE '2025-01-01'`
4. `main.py` calls `executor.run_select(sql)` → SELECT-only guard passes → `python-oracledb` runs query → rows fetched up to cap
5. Response: `{ "sql": "...", "columns": ["COUNT(*)"], "rows": [[42]], "row_count": 1, "elapsed_ms": 87 }`

## Error handling

| Condition | HTTP | Body |
|---|---|---|
| Schema file missing at startup | n/a | exit 1 with log message |
| OpenAI failure / timeout | 502 | `{error: "llm_failed", detail}` |
| Non-SELECT SQL from model | 422 | `{error: "non_select_sql", sql}` |
| Oracle error executing SQL | 500 | `{error: "db_error", detail, sql}` |
| Empty result | 200 | `rows: []` |

## Testing

- **Unit (default `pytest` run, no DB needed):**
  - `tests/test_executor_guard.py` — guard accepts `SELECT`/`WITH`, rejects DML/DDL/multi-statement.
  - `tests/test_schema_loader.py` — load fixture JSON, assert prompt format.
  - `tests/test_llm.py` — monkeypatch the OpenAI client, verify prompt assembly + fence stripping.
- **Manual smoke:** curl `/ask` against the real `WCU_C1002` connection.

## Verification (end-to-end)

1. `cd C:\Users\fdpg8\GitLab\new\nl2sql-agent`
2. `uv venv` → `.venv\Scripts\activate`
3. `uv pip install -r requirements.txt`
4. `cp .env.example .env` and fill keys
5. `sql -name WCU_C1002 @scripts/export_schema.sql > data/schema.json` → file is non-empty
6. `pytest` → all unit tests pass
7. `uv run uvicorn nl2sql_agent.main:app --host 127.0.0.1 --port 8000`
8. `iwr http://127.0.0.1:8000/health -UseBasicParsing` → 200
9. `iwr -Method POST -Uri http://127.0.0.1:8000/ask -Body '{"question":"list 5 tables"}' -ContentType application/json -UseBasicParsing` → returns a valid SELECT and rows
10. Repeat with a real domain question and confirm rows match a hand-written equivalent SQL.

## Out of scope for v1 (deferred)

- ORDS PL/SQL proxy in `obs/english/database/packages/` (v2)
- Authentication, audit logging, rate limiting (v2/prod cut)
- Multi-connection / connection picker (v2)
- Schema-refresh job / periodic reload (v2)
- sqlcl MCP server in the execution path — v1 uses python-oracledb directly (v2 if MCP fidelity becomes a requirement)
- Anthropic Claude provider — v1 is OpenAI-only

# NL2SQL Skills Index

Playbooks the agent can load on demand via the `load_skill` tool. This file is
injected into the system prompt on every model call, so keep descriptions
one-line and trigger-shaped. Add a row for each new file under `skills/`.

| Path | Category | When to load |
|------|----------|--------------|
| skills/plsql/plsql-cursors.md | PL/SQL | Working with implicit/explicit cursors, REF CURSORs, cursor attributes, lifecycle |
| skills/plsql/plsql-collections.md | PL/SQL | Nested tables, VARRAYs, associative arrays, BULK COLLECT, collection methods |
| skills/plsql/plsql-error-handling.md | PL/SQL | EXCEPTION blocks, RAISE_APPLICATION_ERROR, SQLCODE/SQLERRM, propagation rules |
| skills/plsql/plsql-performance.md | PL/SQL | BULK COLLECT, FORALL, context switches, result cache, set-based vs row-by-row |
| skills/plsql/plsql-security.md | PL/SQL | DBMS_ASSERT, AUTHID, SQL injection avoidance, definer vs invoker rights |
| skills/plsql/plsql-package-design.md | PL/SQL | Package spec/body, public vs private API, package state, modular design |
| skills/plsql/plsql-patterns.md | PL/SQL | Table APIs, autonomous transactions, pipelined functions, record types |
| skills/plsql/plsql-debugging.md | PL/SQL | DBMS_OUTPUT, DBMS_DEBUG, conditional compilation tracing, diagnosis techniques |
| skills/plsql/plsql-code-quality.md | PL/SQL | Naming conventions, anti-patterns, static analysis, code review checklist |
| skills/plsql/plsql-compiler-options.md | PL/SQL | PLSQL_OPTIMIZE_LEVEL, conditional compilation, edition-based redefinition |

---

## Usage

When the user's question matches a "When to load" hint above, call:

```
load_skill("skills/plsql/<file>.md")
```

before producing the answer. Paths are relative to the project root (the
FastAPI working directory). Load only the skill files you need — each call
adds to context.

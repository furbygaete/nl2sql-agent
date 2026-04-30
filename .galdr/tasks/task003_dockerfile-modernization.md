---
id: 3
title: 'Modernize Dockerfile (uv + multi-stage + non-root + healthcheck) and add .dockerignore + docker-compose.yml'
status: awaiting-verification
priority: medium
type: infrastructure
subsystems: [deployment]
project_context: 'Container image must build deterministically from `pyproject.toml` + `uv.lock`, run as non-root, and be locally orchestratable so the NL2SQL FastAPI service can be brought up reproducibly with `docker compose up`.'
dependencies: [1, 2]
blast_radius: medium
requires_verification: true
ai_safe: true
spec_version: "1.0"
execution_cost: low
created: 2026-04-29
status_changed: 2026-04-29
tags: []
---

# TASK-003 — Modernize Dockerfile + add .dockerignore + docker-compose.yml

## Goal
Modernize the container build for `nl2sql-agent`:

1. Switch the image from `pip install -r requirements.txt` to `uv sync --frozen --no-dev` so the image matches `pyproject.toml` + `uv.lock` (single source of truth).
2. Use a multi-stage build — builder stage resolves the venv with `uv`, runtime stage gets only the resolved `.venv` plus the Java JRE needed by SQLcl.
3. Run the runtime as a non-root `app` user.
4. Add a `HEALTHCHECK` against the existing `/health` endpoint (`{"status":"ok"}`) using `curl`.
5. Add a comprehensive `.dockerignore` so `.venv/`, `.git/`, `.claude/`, `.cursor/`, `.galdr/`, `.env`, `vendor/sqlcl/`, `memory/`, `__pycache__/`, `.pytest_cache/`, `.nicegui/`, `.sqlcl/`, `tests/`, and `docs/` never enter the build context.
6. Add a `docker-compose.yml` that loads `.env`, mounts host volumes for `./memory` (LangGraph SQLite checkpoints) and `./vendor/sqlcl` (SQLcl binaries), and exposes port `8000`.

## Problems with the current Dockerfile
1. **pyproject/requirements drift** — Dockerfile installs from `requirements.txt` while project metadata + lockfile (`uv.lock`) live with `pyproject.toml`. Two sources of truth diverge silently.
2. **No `.dockerignore`** — build context currently ships `.venv/`, `.git/`, `.claude/`, `.cursor/`, `.galdr/`, `.env`, `vendor/sqlcl/`, `memory/`, etc. into the image, ballooning size and leaking secrets.
3. **No `HEALTHCHECK`** — orchestrators have no signal of liveness even though `/health` exists.
4. **Runs as root** — privilege escalation risk; non-root `app` user is the standard hardening step.
5. **No `docker-compose.yml`** — local bring-up requires bespoke `docker run` invocations.

## Files Touched
| Path | Change |
|---|---|
| `Dockerfile` | Multi-stage rewrite: builder uses `uv sync --frozen --no-dev`; runtime copies `.venv`, installs JRE for SQLcl, adds `app` user + `HEALTHCHECK`. |
| `.dockerignore` | **NEW** — excludes `.env`, `.venv`, `.git`, `.claude/`, `.cursor/`, `.galdr/`, `vendor/sqlcl/`, `memory/`, `__pycache__/`, `.pytest_cache/`, `.nicegui/`, `.sqlcl/`, `tests/`, `docs/`. |
| `docker-compose.yml` | **NEW** — service `nl2sql-agent`, `env_file: .env`, volumes `./memory:/app/memory` and `./vendor/sqlcl:/opt/sqlcl:ro`, port `8000:8000`. |

## Acceptance Criteria
- [ ] `docker build .` succeeds using only `pyproject.toml` + `uv.lock` (no `requirements.txt` reference in the Dockerfile).
- [ ] Final image runs as the non-root `app` user (`docker run --rm <image> id` shows `uid=app`).
- [ ] After startup, `docker inspect --format='{{.State.Health.Status}}' <container>` reports `healthy`.
- [ ] `.dockerignore` excludes every entry listed above; verified via `docker build --no-cache --progress=plain .` showing those paths absent from the transferred context.
- [ ] `docker compose up` reads `.env`, mounts `./memory` and `./vendor/sqlcl` as volumes, and the service is reachable on `http://localhost:8000/health`.
- [ ] Image size of runtime stage is materially smaller than a single-stage build (sanity check; no hard threshold).

## Verification Plan (for the verifying agent / human reviewer)
1. `docker build -t nl2sql-agent:test .` — must succeed.
2. `docker run --rm nl2sql-agent:test id` — assert `uid` is **not** `0` and user is `app`.
3. `docker run -d --name nl2sql-test -p 8000:8000 --env-file .env nl2sql-agent:test`, wait ~30s, then:
   - `curl http://localhost:8000/health` → `{"status":"ok"}`
   - `docker inspect --format='{{.State.Health.Status}}' nl2sql-test` → `healthy`
4. `docker compose config` — validates `docker-compose.yml` syntax.
5. `docker compose up -d && docker compose ps` — service is up; `./memory` and `./vendor/sqlcl` mounted (verify via `docker compose exec nl2sql-agent ls /app/memory /opt/sqlcl`).
6. Inspect built image layers (`docker history nl2sql-agent:test`) — confirm no `.git`, `.claude/`, `.galdr/`, `.env`, or `.venv` from the host context were included.

## Out of Scope
- Pushing the image to a registry.
- Adding GitHub Actions / CI pipeline to build & publish on push.
- Switching to a distroless runtime base.
- Replacing SQLcl with thin-mode `python-oracledb` (tracked separately as a follow-up to task002).

## Status History
| Timestamp | From | To | Message |
|---|---|---|---|
| 2026-04-29 | (new) | awaiting-verification | Implementation done in this session by orchestrator; routed for human verification. |

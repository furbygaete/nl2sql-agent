---
id: SS-05
name: Deployment
type: support
status: active
locations:
  - Dockerfile
  - .dockerignore
  - docker-compose.yml
  - .env.example
spec_version: "1.0"
---

# SS-05 — Deployment

## Purpose
Container build and local orchestration for `nl2sql-agent`. Covers the Dockerfile (multi-stage build using `uv` against `pyproject.toml` + `uv.lock`), the `.dockerignore` that defines the build context, and the `docker-compose.yml` used for local bring-up.

## Locations
- `Dockerfile` — multi-stage image: builder runs `uv sync --frozen --no-dev`; runtime ships `.venv` + JRE for SQLcl, runs as non-root `app` user, has `HEALTHCHECK` against `/health`.
- `.dockerignore` — excludes virtualenvs, IDE config (`.claude/`, `.cursor/`), galdr state (`.galdr/`), VCS (`.git/`), local data (`memory/`), bundled binaries (`vendor/sqlcl/`), tests, docs, and `.env`.
- `docker-compose.yml` — single service `nl2sql-agent`; binds port 8000; mounts `./memory` and `./vendor/sqlcl` from host; loads `.env`.
- `.env.example` — template for required runtime environment variables.

## Boundaries
- Owns container packaging and local orchestration only.
- Does **not** own application code (SS-01 Core Engine), runtime data fixtures (SS-02 Data Assets), or CI/CD pipelines (not yet a registered subsystem).
- Consumes `pyproject.toml` + `uv.lock` to resolve dependencies; consumes `vendor/sqlcl/` as a read-only mount.

## Dependencies
- **SS-01 Core Engine** — packages the FastAPI app and exposes `/health`.
- **SS-03 Automation Scripts** — provides install helpers (e.g., SQLcl bootstrap) that may be invoked from the image build.

## Notes
- Single source of truth for Python deps in the image is `pyproject.toml` + `uv.lock` (no `requirements.txt` install path).
- `.env` is **never** baked into the image — it is supplied at runtime via `--env-file` or the compose `env_file:` directive.

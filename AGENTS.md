# AGENTS.md

Entry point for AI coding agents working in **Foresight**. Read this first, then
read the per-layer context doc in [`agents/`](agents/) for whatever you're touching.
The goal: keep everyone's software practices aligned when they use AI.

## What Foresight is

AI revenue-intelligence platform for boutique hotels. A backend pricing engine
that ingests historical booking data + external demand signals (events, weather,
flights, competitor pricing) and produces explainable room-rate recommendations.

## Stack

Python · FastAPI · async SQLAlchemy 2.0 · Alembic · Postgres · uv · Docker ·
GitHub Actions · ruff · Conventional Commits.

## Architecture — n-tier, never skip a layer

```
routes  →  services  →  repository  →  database
```

- **routes** — HTTP layer (FastAPI routers, request/response via Pydantic schemas).
- **services** — business logic, orchestration, ML/parsers.
- **repository** — data access; the only layer that talks to the ORM/session.
- **database** — SQLAlchemy models, migrations, session/engine.

Rule: a layer may only call the layer directly below it. Routes never touch the
ORM; services never build HTTP responses. Code lives in the installable package
`backend/foresight/`.

There's a working reference slice to copy — the `Widget` example threads all
four layers (`example_widget.py` in each). Each doc below points to its file.

Per-layer detail:
- [`agents/routes.md`](agents/routes.md)
- [`agents/services.md`](agents/services.md)
- [`agents/repository.md`](agents/repository.md)
- [`agents/database.md`](agents/database.md)

## Commands (run from repo root)

```bash
just dev              # db + backend with hot reload
just migrate          # apply migrations
just migrate-create "msg"   # new Alembic migration after model changes
just migrate-down     # roll back last migration
just lint             # ruff checks
just format           # ruff format
```

API: http://localhost:8000 · docs: http://localhost:8000/docs

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`…).
- **Lint/format:** ruff must pass before commit; pre-commit hooks are enforced.
- **Migrations:** any model change needs an Alembic migration that applies *and*
  rolls back cleanly.
- **Config:** add new settings to `config.py` and document them in `.env.example`.
- **Keep docs current:** if you change a layer's patterns, update that layer's
  file in `agents/`.

## Do / don't for agents

- **Do** follow the existing pattern in the layer you're editing — read its
  `agents/` doc before writing code.
- **Do** keep business logic in services and data access in the repository.
- **Don't** skip layers, add dependencies without updating `pyproject.toml`, or
  change the schema without a migration.
- **Don't** invent new conventions; this file and `agents/` are the source of truth.

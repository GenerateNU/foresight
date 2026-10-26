# AGENTS.md

Entry point for AI coding agents working in **Foresight**. Read this first, then
[`docs/system-design.md`](docs/system-design.md) for how the backend fits
together, and the [decision records](docs/decisions/README.md) for the code
you're touching.
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

- **routes** — HTTP layer: FastAPI routers and the `*Request`/`*Response`
  schemas each one uses.
- **services** — business logic: `domain/`, `ingest/`, `adapters/`, `ml/`,
  `job.py`.
- **repository** — data access; the only layer that talks to the ORM/session.
- **database** — SQLAlchemy models, migrations, session/engine.

Rule: a layer may only call the layer directly below it. Routes never touch the
ORM; services never build HTTP responses. Code lives in the installable package
`backend/foresight/`.

There's a working reference slice to copy — the `Widget` example threads all
four layers (`example_widget.py` in each).

## Commands (run from repo root)

```bash
just dev              # db + backend with hot reload (local Docker Postgres)
just dev --neon       # same, against Neon; `--neon` works on run/migrate*/test too
just migrate          # apply migrations
just migrate-create "msg"   # new Alembic migration after model changes
just migrate-down     # roll back last migration
just link-user <email> <hotel_id>   # link a user to a hotel (`--neon` works too)
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
- **Keep docs current:** if you change how the system fits together, update
  [`docs/system-design.md`](docs/system-design.md).
- **Decisions:** design decisions live in [`docs/decisions/`](docs/decisions/),
  one per file. Read the relevant record before changing that code; record new
  decisions there.

## Do / don't for agents

- **Do** follow the existing pattern in the layer you're editing — see
  `docs/system-design.md` and the `Widget` slice before writing code.
- **Do** keep business logic in services and data access in the repository.
- **Don't** skip layers, add dependencies without updating `pyproject.toml`, or
  change the schema without a migration.
- **Don't** invent new conventions; this file, `docs/system-design.md` and
  `docs/decisions/` are the source of truth.

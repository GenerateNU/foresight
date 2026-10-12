# Architecture Overview

Quick note before anything else:

We're throwing a *lot* of information at you at once — new concepts, new tech, new patterns.
It is **not expected** that this all makes sense right away. If even ~10% clicks at first, that's totally fine.

The goal of this doc is just to give you a **high-level mental model** of how things are structured.
You'll build real understanding by working on tickets and asking questions ‼️‼️‼️ (please do).

> For AI coding agents: start with [`AGENTS.md`](AGENTS.md), then read the per-layer
> context docs in [`agents/`](agents/).

---

## What Foresight Is

Foresight is an **AI revenue-intelligence platform for boutique hotels**. The backend is a
pricing engine that ingests historical booking data plus external demand signals (events,
weather, flights, competitor pricing) and produces explainable room-rate recommendations.

**Stack:** Python · FastAPI · async SQLAlchemy 2.0 · Alembic · Postgres · uv · Docker ·
GitHub Actions · ruff · Conventional Commits.

The project is **backend-only today** — `frontend/` is a placeholder (TBD).

---

# Backend Architecture

## High-Level Idea

Foresight's backend follows a **layered (N-tier) architecture**.

Most requests flow like this:

```
Client → Route → Service → Repository → Database
```

You don't need to memorize this — you'll see the pattern everywhere.

---

## What Each Layer Does

### Routes (API / HTTP layer)
- Define API endpoints (`GET /health`, `POST /example/widgets`, etc.)
- Handle HTTP stuff (requests, responses, status codes)
- Validate input and shape output via Pydantic **schemas**
- Call the service layer

They should **not**:
- Contain business logic
- Talk directly to the ORM, session, or repository

Each router is an `APIRouter` (one module per resource) and must be registered in
`foresight/main.py` via `app.include_router(...)`.

---

### Services (business logic)
- Where most of the "thinking" happens
- Apply rules, validation, and transformations
- Orchestrate use cases, run the pricing/ML logic and data parsing
- Call repositories when data is needed

If you're unsure where code should live, it usually belongs here.

Two focused sub-areas live under `services/`:
- `services/ml/` — modeling / recommendation logic (regression, bayesian, timeseries, neural net).
- `services/parsers/` — ingesting external + hotel data.

---

### Repository (data access)
- The **only** layer that talks to the ORM and the async SQLAlchemy session
- Turns domain requests from services into queries
- Returns ORM models / simple data back up

Functions are `async` and receive an `AsyncSession` (they don't open their own).
Think of this as a clean interface between Python code and the DB.

---

### Database
- SQLAlchemy models, the async engine/session, and Alembic migrations
- Defines *what* the data looks like (the repository decides *how* it's queried)
- Async SQLAlchemy 2.0 style (typed, `Mapped[...]`), all models on a shared declarative base
- Every schema change ships with an Alembic migration

---

## Folder Mapping

How this shows up in `backend/`:

```
backend/
├── foresight/                 # Installable package (foresight.main:app)
│   ├── main.py                # FastAPI app entrypoint; routers registered here
│   ├── config.py              # Settings (pydantic-settings)
│   ├── routes/                # API endpoints (one module per resource)
│   ├── schemas/               # Pydantic *Request/*Response schemas (agents/schemas.md)
│   ├── services/              # Business logic
│   │   ├── ml/                # ML models (regression, bayesian, timeseries, ...)
│   │   └── parsers/           # Client/external data ingestion
│   ├── repository/            # Data-access layer (ORM/session only here)
│   └── database/              # SQLAlchemy + Alembic
│       ├── base.py            # Declarative base
│       ├── session.py         # Async engine + session factory (get_session)
│       ├── models/            # SQLAlchemy models (hotel.py, external.py, ...)
│       └── migrations/        # Alembic env + versions/
├── scripts/                   # Dev tooling (mock data, model comparison)
├── tests/                     # Pytest suite
├── alembic.ini
├── pyproject.toml
└── Dockerfile
```

There's a working **reference slice** to copy — the `Widget` example threads all four
layers (`example_widget.py` in `routes/`, `services/`, `repository/`, `schemas/`, and
`database/models/`). Start there.

---

## Dependency Rule (Important)

Dependencies should only flow **downward**, and a layer may only call the layer directly
below it:

```
route → service → repository → database
```

Avoid:
- Routes importing the ORM, session, or repository directly
- Services touching the ORM/session or building HTTP responses
- Repositories containing business logic or HTTP concerns

If you're unsure whether something breaks this rule, just ask.

---

## Example Request Flow

Rough idea of what happens when a request comes in:

1. Route receives the request and validates the body against a schema
2. Route calls a service function (passing the injected `AsyncSession`)
3. Service applies logic and calls a repository
4. Repository runs the query against the database
5. Result flows back up; the route maps it to a response schema and returns it

You'll see this pattern everywhere.

---

# Commands

Run from the repo root (uses [`just`](https://github.com/casey/just)):

```bash
just dev              # db + backend with hot reload (docker compose up -d)
just build            # build/rebuild the backend image
just logs             # tail backend logs
just destroy          # stop everything

just migrate          # apply migrations
just migrate-create "msg"   # new Alembic migration after model changes
just migrate-down     # roll back last migration

just test             # run the pytest suite
just lint             # ruff checks
just format           # ruff format
just fix              # ruff --fix + format
just hooks            # install pre-commit hooks
```

API: http://localhost:8000 · docs: http://localhost:8000/docs

---

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`…).
- **Lint/format:** ruff must pass before commit; pre-commit hooks are enforced.
- **Migrations:** any model change needs an Alembic migration that applies *and* rolls back cleanly.
- **Config:** add new settings to `config.py` and document them in `.env.example`.
- **Keep docs current:** if you change a layer's patterns, update that layer's doc in `agents/`.

---

## Final Notes

If this feels overwhelming, that's normal. You're not expected to understand all of this immediately.

Understanding comes from:
- Reading the `Widget` example slice
- Working on small pieces
- Asking questions ‼️‼️‼️‼️‼️‼️‼️‼️‼️‼️‼️‼️

This doc is just here to give you a map — not to test you.

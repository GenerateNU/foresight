# Database — Agent Context

**Updated:** 2026-10-06

## Purpose
The persistence foundation: SQLAlchemy models, the async engine/session, and
Alembic migrations. Defines *what* the data looks like; the repository layer
decides *how* it's queried.

## Key files
- `backend/foresight/database/models/` — ORM models (`hotel.py`, `external.py`).
- `backend/foresight/database/base.py` — declarative base.
- `backend/foresight/database/session.py` — async engine + session factory.
- `backend/foresight/database/migrations/` — Alembic env + `versions/`.

## Patterns & conventions
- Async SQLAlchemy 2.0 style (typed, `Mapped[...]`), all models on the shared base.
- Every schema change ships with an Alembic migration generated via
  `just migrate-create "msg"`.
- Engine/session config is driven by `config.py` settings.

## Rules / invariants
- No business logic or queries here — models and wiring only (queries live in
  `repository/`).
- Never edit the DB schema without a migration that applies and rolls back.
- New models must be imported where Alembic autogenerate can see them.

## Reference example
Copy the pattern in `backend/foresight/database/models/example_widget.py` plus
its migration in `database/migrations/versions/*_example_widget.py`.

## How to verify
`just migrate` (apply) then `just migrate-down` (roll back) run cleanly; `just lint`.

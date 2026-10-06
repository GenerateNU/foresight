# Repository — Agent Context

**Updated:** 2026-10-06

## Purpose
The data-access layer. The **only** layer that talks to the ORM and the async
SQLAlchemy session. It turns domain requests from services into queries and
returns models/data back up. No business rules, no HTTP.

## Key files
- `backend/foresight/repository/` — query/persistence functions per aggregate.
- `backend/foresight/database/session.py` — `get_session()` / session factory.
- `backend/foresight/database/models/` — the ORM models being queried.

## Patterns & conventions
- Functions are `async` and receive an `AsyncSession` (don't open their own).
- Encapsulate all query/CRUD logic here so services stay persistence-agnostic.
- Return ORM models or simple data; let callers map to schemas.

## Rules / invariants
- Only this layer imports `session` / ORM query APIs.
- No business logic and no HTTP concerns.
- Don't manage transactions ad hoc — use the session provided via `get_session()`.

## Reference example
Copy the pattern in `backend/foresight/repository/example_widget.py` (the
canonical repository pattern).

## How to verify
Exercise via a service + test, or through an endpoint with `just dev`. `just lint`.

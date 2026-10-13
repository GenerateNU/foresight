# Services — Agent Context

**Updated:** 2026-10-06

## Purpose
The business-logic layer. Orchestrates use cases, runs the pricing/ML logic and
data parsing, and composes repository calls. Services are the only place where
domain rules live — they're called by routes and call the repository.

## Key files
- `backend/foresight/services/` — business logic modules.
- `backend/foresight/services/ml/` — modeling / recommendation logic.
- `backend/foresight/services/parsers/` — ingesting external + hotel data.
- `backend/foresight/ingest/` — external-source adapters (events, weather,
  flights). Part of the services layer: they fetch and normalize, then write
  through `repository/`.
- `backend/foresight/services/backfill/` — fetch an external source over a date
  range and save it. Long runs yield after each unit of work (a month of events,
  a day of flights) so the CLIs in `backend/scripts/backfill/` can commit as
  they go.

## Patterns & conventions
- Pure-ish domain functions/classes; take plain inputs or `*Request` schemas,
  return domain data (ORM objects or dataclasses) — never `*Response` schemas.
  See [`schemas.md`](schemas.md).
- Parse external API responses into `ExternalPayload` models in the module that
  calls the API.
- Get data through the repository layer; don't query the ORM here.
- Keep ML, parsing, and orchestration in focused modules; prefer small units.

## Rules / invariants
- No FastAPI/HTTP concerns (no `Request`, no status codes, no routers).
- No direct ORM/session use — all persistence goes through `repository/`.
- External API access and heavy logic belong here, not in routes.
- Never open a session or commit. CLIs live in `backend/scripts/`; they open the
  session, call the service, and commit once.

## Reference example
Copy the pattern in `backend/foresight/services/example_widget.py`.

## How to verify
Add/adjust unit tests under `backend/tests/` and run the suite; `just lint`.

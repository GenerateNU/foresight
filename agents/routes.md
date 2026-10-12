# Routes — Agent Context

**Updated:** 2026-10-06

## Purpose
The HTTP layer. Defines FastAPI routers, validates input and shapes output via
Pydantic schemas, and delegates all real work to **services**. No business logic
and no database access here.

## Key files
- `backend/foresight/routes/` — one module per resource (e.g. `health.py`).
- `backend/foresight/main.py` — app setup; routers registered with
  `app.include_router(...)`.
- `backend/foresight/schemas/` — Pydantic request/response models used here.

## Patterns & conventions
- One `APIRouter` per module, with `tags=[...]`; include it in `main.py`.
- Handlers are `async def`. Type request bodies and responses with schemas.
- Call into services; translate service results into responses. Keep handlers thin.

## Rules / invariants
- Never import the ORM, session, or repository directly — go through a service.
- No SQL, no business rules in this layer.
- Every new router must be registered in `main.py`.

## Reference example
Copy the pattern in `backend/foresight/routes/example_widget.py` (the `Widget`
vertical slice: `database -> repository -> service -> route`).

## How to verify
`just dev`, then hit the endpoint via http://localhost:8000/docs. Run `just lint`.

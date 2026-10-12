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
- `backend/foresight/schemas/` — Pydantic `*Request` / `*Response` models used
  here. See [`schemas.md`](schemas.md) for the standard.

## Patterns & conventions
- One `APIRouter` per module, with `tags=[...]`; include it in `main.py`.
- Handlers are `async def`. Take bodies as `*Request` schemas; declare
  `response_model=` with a matching `*Response` return type.
- Inject the session as `Depends(get_session, scope="function")` (see
  `SessionDep` in the widget example). It commits once per request after the
  handler returns; handlers and services never commit.
- Call into services; build the response with `XxxResponse.model_validate(result)`.
  Keep handlers thin.

## Rules / invariants
- Never import the ORM, session, or repository directly — go through a service.
- No SQL, no business rules in this layer.
- Every new router must be registered in `main.py`.

## Reference example
Copy the pattern in `backend/foresight/routes/example_widget.py` (the `Widget`
vertical slice: `database -> repository -> service -> route`).

## How to verify
`just dev`, then hit the endpoint via http://localhost:8000/docs. Run `just lint`.

# 0014. Services raise domain errors; one place maps them to HTTP

**Status:** Accepted · **Date:** 2026-10-15

## Context
"Not found" was handled two ways: some lookups returned None and the route
raised a 404, others raised inside the service. Status codes were scattered.

## Decision
- Services raise errors from `services/errors.py`:
  - `NotFoundError` → 404
  - `ConflictError` → 409
  - `InvalidRequestError` → 422
  - `NotConfiguredError` (an API key isn't set) → 503
- Every `get_x(id)` raises `NotFoundError` rather than returning None.
- `routes/errors.py` is the only place that turns an error into a status code.
  Routes never check for None and never catch domain errors.
- Every error body is `{"detail": "..."}`, the same shape as FastAPI's own.

## Consequences
- A route handler is three lines: parse, call, map.
- The repository still returns None for a missing row or a duplicate insert.
  Deciding that this is an error is the service's job.

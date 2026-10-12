# Schemas — Agent Context

**Updated:** 2026-10-12

## Purpose
Pydantic models that validate and convert data at the edges of the app: HTTP
requests and responses, and payloads from external APIs. They are not the
database models (those are SQLAlchemy, in `database/models/`) and they are not
for passing data between our own functions.

## Key files
- `backend/foresight/schemas/base.py` — `RequestSchema`, `ResponseSchema`,
  `ExternalPayload` base classes.
- `backend/foresight/schemas/<resource>.py` — HTTP schemas, one module per resource.
- `backend/foresight/schemas/example_widget.py` — reference example.

## When to use Pydantic
| Data | Use |
|---|---|
| HTTP request body | `<Name>Request(RequestSchema)` |
| HTTP response body | `<Name>Response(ResponseSchema)` |
| Payload from an external API | `<Source><Name>Payload(ExternalPayload)` |
| Config | `pydantic-settings` (`config.py`) |
| Data passed between our own functions | ORM object or `@dataclass` — **not** Pydantic |

Create one schema per distinct shape that crosses a boundary — not one per table.
A table never sent over HTTP needs no schema.

## Patterns & conventions
- **Naming by direction:** `<Name>Request` for what a client sends,
  `<Name>Response` for what an endpoint returns. Only create a `Request` if the
  endpoint takes a body.
- **Base classes:**
  - `RequestSchema` — `extra="forbid"`: unknown fields are rejected with a 422.
  - `ResponseSchema` — `from_attributes=True`: build it from an ORM object with
    `XxxResponse.model_validate(obj)`.
  - `ExternalPayload` — `extra="ignore"`: external APIs add fields; we only
    model what we use.
- **No inheritance between Request and Response.** Each lists its fields
  explicitly. Duplication is fine; it keeps input fields from silently leaking
  into output.
- **Nested items** follow the same naming (e.g. `ContributionResponse` inside
  `RecommendationResponse`).
- **Fields:** `Decimal` for money, `date`/`datetime` for time. Use
  `Field(description=..., ge=..., le=...)` for constraints and docs — they show
  up in `/docs`. Use `@computed_field` for values derived from other fields.

## How each layer uses them
- **Routes** take `Request` schemas as parameters, declare `response_model=`,
  and build the `Response` with `model_validate(...)`.
- **Services** may take a `Request` schema as input. They return ORM objects or
  dataclasses — never `Response` schemas (services don't build HTTP responses).
- **Repository** never imports schemas; it takes plain values.
- **External API clients** (services) parse raw responses into `ExternalPayload`
  models, then map them to domain objects/ORM models. Payload models live in the
  module that calls the API, not in `schemas/`.

## Rules / invariants
- Every route declares `response_model=` and a matching return type.
- Never return an ORM object's sensitive/internal fields — only what the
  `Response` declares is sent.
- No business logic in schemas beyond simple `@computed_field` derivations.

## Reference example
Copy the pattern in `backend/foresight/schemas/example_widget.py`.

## How to verify
`just dev`, check the schemas at http://localhost:8000/docs. Run `just lint`.

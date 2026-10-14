# 0015. HTTP schemas live in the route that uses them

**Status:** Accepted · **Date:** 2026-10-15

Supersedes [0011](0011-pydantic-at-boundaries.md).

## Context
A separate `schemas/` layer let services accept `*Request` objects, which tied
business logic to the HTTP shape. The `ExternalPayload` base for outside APIs
was never used.

## Decision
- Pydantic is used only for HTTP bodies and for config.
- Each route module defines the `*Request`/`*Response` schemas it uses, on two
  bases in `routes/helpers.py`:
  - `RequestSchema` rejects unknown fields.
  - `ResponseSchema` builds from an ORM object or a dataclass.
- Request and Response never inherit from each other.
- Services take plain arguments and return ORM objects or dataclasses. They
  never see a schema.
- Data from outside APIs is parsed into dataclasses (`NormalizedEvent`) or
  plain row dicts.

## Consequences
- The HTTP shape can change without touching a service.
- A response that is reused across routes is imported from the route that
  owns it (`HotelResponse` nests `CityResponse` from `routes/city.py`).

# 0011. Pydantic only at boundaries, named Request/Response

**Status:** Accepted · **Date:** 2026-10-13

## Context
Schemas followed a `*Create` / `*Read` pattern, one pair per table, with `Read`
inheriting from `Create`. That creates boilerplate for tables never sent over
HTTP, and inheritance silently copies input fields into output.

## Decision
- Use Pydantic only where data enters or leaves the app: HTTP requests and
  responses, external API payloads, config. Internal data uses ORM objects or
  dataclasses.
- One schema per distinct shape that crosses a boundary, not one per table.
- Name by direction: `<Name>Request`, `<Name>Response`,
  `<Source><Name>Payload`. No inheritance between Request and Response.
- Shared bases in `schemas/base.py`: `RequestSchema` (`extra="forbid"`),
  `ResponseSchema` (`from_attributes=True`), `ExternalPayload`
  (`extra="ignore"`).
- Services may take `Request` schemas but never return `Response` schemas; the
  repository never imports schemas.

Full standard: [`agents/schemas.md`](../../agents/schemas.md).

## Consequences
- Widget and hotel schemas were converted.
- Branch 38 (API ticket) still uses `*Read`/`*Create`; its schemas and imports
  need converting when it merges.
- `ingest/` still parses PredictHQ and AskNews into dataclasses; converting
  them to `ExternalPayload` is a separate refactor.

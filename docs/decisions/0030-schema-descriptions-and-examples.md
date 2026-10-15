# 0030. Every field is described; examples are built from the fields

**Status:** Accepted · **Date:** 2026-10-15

## Context
`/docs` was inconsistent. Most response fields and every path id had no
description, units were missing (°C, mm, km/h, EUR), and examples were written
three different ways. Only two request bodies showed a filled-in example, and
those were written by hand, so they could disagree with the fields' defaults.

## Decision
- Every request field, response field, path id and query parameter has a
  `description`. Units, inclusive dates, currency and what `null` means go
  there; example values never do.
- Example values go in `examples=` and are neutral placeholders ("Example
  City", "XX", 12.34, 2025-01-01), not real hotel data.
- A field with a default has no separate example: the default is what
  `/docs` shows. `limit`/`offset` show 50 and 0, `activate` shows true.
- `RequestSchema` builds each body's example from its fields
  (`example_body` in `routes/helpers.py`): the default where there is one,
  else the example. Nobody writes a body example by hand, so it can't drift.
- Fields whose value changes what a request does (the EBM `settings`) carry
  no example, so the default body never sets them.
  They're shown in the endpoint's picker instead.
- Endpoints with several modes (ingest, train) keep a picker. Its first entry
  is the generated body; the others are derived from it.
- A PATCH body reuses its create body's field settings (module-level dicts of
  `Field` kwargs). The "cannot be null" check and the `start`/`end` query
  parameters stay in each module rather than in shared helpers.
- Route modules use boxed `Schemas` and `Endpoints` section headers.

## Consequences
- Changing a field's default or example changes the body `/docs` shows, with
  nothing else to update.
- Real values for local testing come from the API, not from `/docs`.

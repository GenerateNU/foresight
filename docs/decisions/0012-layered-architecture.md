# 0012. Four layers, each calling only the one below

**Status:** Accepted · **Date:** 2026-10-15

## Context
Without a fixed structure, HTTP handling, business rules and queries end up
mixed together, and every change touches everything.

## Decision
The backend is four layers, in this order:

```
routes  →  services  →  repository  →  database
```

- **routes**: HTTP only. Parse the request, call one service, map the result.
- **services**: business rules, orchestration, outside APIs, the model.
- **repository**: the only code that queries or writes the database.
- **database**: tables, enums, constraints, migrations, the session.

A layer calls only the layer directly below it. Enums live in the database
layer, because columns use them, and every layer may import them.

## Consequences
- Routes never touch the ORM. Services never build HTTP responses or know
  about status codes. The repository never holds business rules.
- Each layer can be tested on its own. Adapters to outside APIs are tested
  without a database (see [0016](0016-services-split-by-role.md)).

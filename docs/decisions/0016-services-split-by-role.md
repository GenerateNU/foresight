# 0016. Services are split into domain, adapters, ingest and ml

**Status:** Accepted · **Date:** 2026-10-15

## Context
The services layer mixed four kinds of code: domain rules, outside API
clients, fetch-and-save runs, and the model. The folders didn't show which
could call which.

## Decision
```
services/
  domain/    rules and reads for one domain (hotel, city, event, ...)
  adapters/  one outside source each: call it, return plain data. No database.
  ingest/    fetch through an adapter and save through the repository, in chunks
  ml/        the pricing model; pure functions and classes
  job.py     job kinds and lifecycle
  errors.py  domain errors
```

- Adapters never touch the database.
- Ingest never commits; it yields after each chunk so the job runner can.

## Consequences
- An adapter can be tested with a mock HTTP transport and no database.
- Adding a data source means adding one adapter and one ingest module.

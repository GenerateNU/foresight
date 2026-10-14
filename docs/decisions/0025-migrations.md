# 0025. Linear migrations that always roll back

**Status:** Accepted · **Date:** 2026-10-15

## Context
The migration history had branched, and constraint names had been generated
by Postgres, so migrations couldn't refer to them reliably.

## Decision
- Alembic history is linear: one head.
- Every model change has a migration that applies and rolls back. Its
  docstring says why the change exists and what happens to existing data.
- Constraints and indexes are named by a naming convention on
  `Base.metadata`, and upserts target them by name.
- Every foreign key states its `ON DELETE` rule.
- CI checks for one head, that the models match the migrations, and a full
  downgrade and upgrade.

## Consequences
- Any migration can be undone in development and production alike.

# 0018. Every outside write is an upsert on a natural key

**Status:** Accepted · **Date:** 2026-10-15

## Context
Jobs stop part-way and get re-run, and windows overlap. Re-running must
never duplicate data.

## Decision
- Every write from an outside source or file is an upsert keyed on what the
  row describes. Examples: city + day + source for weather, room type + night
  for performance.
- `repository/upsert.py` is the shared bulk upsert. It rewrites a row only
  when a value changed, and reports new, updated and unchanged counts.
- Each source keeps its own row. Deciding which source wins is done when the
  data is read for the model, not when it is written.

## Consequences
- Any job or import can be run again safely. Overlap costs API calls, not
  correctness.
- Reads for the model must pick one value per night from several sources.

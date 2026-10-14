# 0019. Events are merged across sources; raw sightings are kept

**Status:** Accepted · **Date:** 2026-10-15

## Context
The same real-world event can be listed by PredictHQ and reported in the
news. Pricing needs it counted once, and sources revise or withdraw events
over time.

## Decision
- `events` holds one canonical row per real-world event, identified by a
  dedupe key: normalized title + city + local start date.
- `event_observations` keeps every source's raw record, verbatim and keyed on
  the source's own id.
- When sightings disagree, the row carries the values of the highest-ranked
  sighting. Ranking order:
  1. structured listings over text extraction
  2. live over withdrawn
  3. newest revision
- The rule lives in `services/domain/event.py`.

## Consequences
- An event can be re-derived from its observations if the merge rule changes.
- A revision that moves an event onto another event's key merges the two rows.

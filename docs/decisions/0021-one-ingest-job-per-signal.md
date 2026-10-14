# 0021. One ingest job per signal; the dates decide refresh or backfill

**Status:** Accepted · **Date:** 2026-10-15

## Context
There were separate "ingest" and "backfill" endpoints and job kinds per
source, each with its own date rules.

## Decision
Each signal has one endpoint and one job kind,
`POST /hotels/{id}/ingest/{weather,events,performance}`.

- **No dates**: the signal's routine refresh.
  - Weather: the 16-day forecast.
  - Events: what PredictHQ revised since the last refresh.
- **Any date**: a backfill over a window.
  - start and end: that window.
  - start only: from start to today.
  - end only: back from end to the hotel's first loaded night, newest first.
- Performance takes one or more client CSV files and parses them all before
  the job is queued.

## Consequences
- The word "backfill" describes a mode, not an endpoint.
- Walking backwards from `end` saves the most recent data first if a quota
  runs out.

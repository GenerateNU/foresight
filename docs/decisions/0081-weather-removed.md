# 0081. Weather is removed; its table is kept for now

**Status:** Accepted · **Date:** 2026-11-20 · Amends [0051](0051-calendar-only-model.md),
[0055](0055-events-back-in-the-model.md)

## Context
Weather has been out of the model since [0051](0051-calendar-only-model.md),
and [0055](0055-events-back-in-the-model.md) said its ingestion would be
removed later. Experiments found it doesn't move the price. It was still
fetched from Open-Meteo, stored, listed and checked for gaps, with routes, a job
kind and a freshness entry that nothing in pricing used.

Neon holds 1,494 weather days. Whether to delete them isn't decided yet.

## Decision
- **Weather is removed**: the Open-Meteo adapter, the ingest, the weather and
  weather-coverage services, the repository, the model,
  `POST /hotels/{id}/ingest/weather`, `GET /hotels/{id}/weather`,
  `GET /hotels/{id}/coverage/weather`, the weather job handler and the
  `weather` entry in freshness. `Window.years` and `Window.clip`, used only by
  the weather job, go too.
- **The disabled "Weather" colour mode in the calendar is removed.**
- **The table and its rows stay** until the team decides. Alembic ignores the
  table (`RETIRED_TABLES` in `migrations/env.py`), as it does
  `daily_performance` (0080).
- **`JobKind.WEATHER` stays in the enum**, so old job rows still load, but
  nothing queues it.
- **Cities keep their coordinates and timezone**: events are searched at the
  centre, and every "today" is local.

## Consequences
- The model's inputs are unchanged: weather never reached it.
- Old snapshots that stored weather inputs keep them; nothing reads them.
- `GET /hotels/{id}/freshness` no longer has a `weather` field.
- Deleting the data needs: the 1,494 weather days, the 7 `WEATHER` job rows,
  and then the enum member and `RETIRED_TABLES` entry.
- `httpx` stays a dependency: the PredictHQ adapter uses it.

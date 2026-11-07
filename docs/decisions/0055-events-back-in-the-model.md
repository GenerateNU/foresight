# 0055. Events are back in the model, counted from when PredictHQ first saw them

**Status:** Accepted · **Date:** 2026-11-07

Partly supersedes [0051](0051-calendar-only-model.md): events come back,
weather stays out. Restores [0041](0041-events-in-the-model.md) and
[0032](0032-events-on-a-night-follow-the-model.md).

## Context
0051 took weather and events out of the model until experiments showed they
helped. The team's backtests now show events do, so they come back. Weather
doesn't matter to us, so it stays out of the model; its ingestion is removed
later.

Training on past nights has a leak: PredictHQ adds some events late,
sometimes after they happen. A model that counts those learns from demand
nobody could have priced for.

## Decision
- **The event inputs from 0041 are back:** the public and school holiday
  flags, `event_count`, `event_attendance`, `event_rank_max`,
  `event_accommodation_impact`, `big_event_count` and `nearest_big_event_km`.
  `FEATURES` is the calendar plus these.
- **Unknown, not quiet, as in 0041.** A night no events backfill covered
  (`event.fetched_nights`) gets empty event inputs, not zeros.
- **First seen.** An event counts on a night, including its accommodation
  impact, only if PredictHQ's `first_seen` date is before that night.
  `first_seen` is read from the event's stored raw record
  (`predicthq.first_seen`). PredictHQ describes it as when the event entered
  its dataset, not as an announcement date, so it is the earliest date we can
  show the event was knowable. An event without it always counts. Our own
  `events.first_seen_at` isn't used: for past nights it is the date of our
  backfill, after the night, so it would drop every historical event.
- **Recommendations show events again,** with `events` and `events_source` per
  night as in 0032 and 0041. Each night's fingerprint includes its events, so
  a new or changed event re-prices the night (0038). `weather_source` stays
  removed.
- **The backtest** takes the events group in `--inputs` again, and
  `--event-days` limits how much event history it trains on.

## Consequences
- **Retrain every hotel.** Models trained under 0051 expect only the calendar.
- Future nights only count as covered once a backfill has fetched them, so a
  backfill of the next ~90 days has to run regularly. Until a scheduled
  refresh exists, it is run by hand (`POST /hotels/{id}/ingest/events` with
  dates).
- On serving, every stored event was first seen before an upcoming night, so
  the first-seen rule only changes training. Training and serving still build
  features with the same code.
- A night's first-seen cut-off is the night itself, not a booking lead time.
  If the backtest shows events added a few days before a night still leak, a
  lead time can be added in `ml/features._known_before`.
- No automated tests: the test suite was removed from `main`. The rules were
  checked by running `build_features` on hand-made events.

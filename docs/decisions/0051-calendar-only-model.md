# 0051. The model reads only the calendar until experiments say otherwise

**Status:** Accepted · **Date:** 2026-11-07

Supersedes [0024](0024-weather-for-future-nights.md),
[0032](0032-events-on-a-night-follow-the-model.md) and
[0041](0041-events-in-the-model.md).

## Context
Weather and events went into the model before anything showed they helped,
and each added code to every path: a loader per signal, rules for unknown
nights, a typical-weather fallback, per-night event lists and source labels on
every recommendation, and `--event-days` in the backtest. Input experiments
are moving to notebooks, where trying an input shouldn't mean wiring it
through training, serving and snapshots first.

## Decision
- `FEATURES` is `room_type`, `day_of_week` and `month`. `build_features`
  takes only the nights.
- Weather and events are still ingested, stored and listed by their own
  routes; the adapters, jobs and tables stay. Nothing in training, the
  backtest or recommendations reads them.
- Removed: `domain/model_inputs.py`, the event and weather feature code, the
  per-night event rule (`counted_events`, `fetched_nights`,
  `events_by_night`), the repository reads only they used, `--event-days`,
  and `events`, `weather_source` and `events_source` on a recommendation.
- Everything else in the model stays: feedback, the interval, uncertainty,
  snapshots, weighting, training cost and the backtest.

## Consequences
- **Retrain every hotel.** Models trained before this expect the old inputs.
- A snapshot's `inputs` now holds only `features`. Older snapshots keep
  their events and weather in the JSON; nothing reads them.
- An input comes back by showing it helps in a notebook backtest, then adding
  it to `FEATURES` and `build_features`. The removed code is in git history.

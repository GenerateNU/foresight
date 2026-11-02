# 0040. Events reach the model; nights no backfill covered are unknown

**Status:** Accepted · **Date:** 2026-11-01

Updates [0028](0028-train-and-serve-on-ingested-data.md) (events are no longer
passed empty) and [0007](0007-shared-feature-builder.md) (event inputs).

## Context
Training and recommendations passed an empty events table (`NO_EVENTS`), so
the event inputs were always zero. Filling them naively has a trap: a night
we never fetched events for looks the same as a night with no events, which
teaches the model that events don't matter. PredictHQ's plan only returns
the last 90 days, so event history starts late and grows as nights pass.

## Decision
- **Which events count:** active and provisional; cancelled and deleted
  don't. `event.counted_events` is the one rule, used both by the model and
  for the events shown on a night (0032).
- **Unknown, not quiet:** `event.fetched_nights` works out which nights an
  events backfill covered, per city, from the city's finished window jobs.
  `build_features(..., events_fetched=...)` leaves the event columns empty
  on every other night, like missing weather.
  - Only backfills count. A backfill asks for every event in its dates; the
    routine refresh only asks what changed, so it can't say any night's list
    is complete.
  - A job counts for the months it saved (`months_done`), so a job that
    ended early still counts for its finished months.
  - Months PredictHQ cut short (`overflowed_months`) or that came back empty
    (`empty_months`) don't count: a month with nothing points to a plan
    limit, not a quiet city. Jobs from before `empty_months` existed count
    only if they fetched something.
- **Each night says where its events came from:** `events_source` is
  `fetched` or `missing`, stored with the snapshot's inputs, like
  `weather_source`.
- **Inputs:** the existing `event_count`, `event_attendance` and
  `event_rank_max`, plus:
  - `event_accommodation_impact`: PredictHQ's accommodation impact summed
    per night, including the nights before and after each event.
  - `big_event_count`: events whose predicted accommodation spend is at
    least 100k. The threshold is a starting point from 14 Dublin nights;
    the backtest should also try attendance of at least 10,000 instead.
  - `nearest_big_event_km`: how far the night's closest big event is from
    the hotel, in km. Empty when there's no big event or the hotel has no
    coordinates, so the backtest can show whether distance matters.
- **Testing:** all of them start in the model, and the ones the backtest
  finds don't help are removed.
- **Not added:** attendance by category (accommodation spend already weights categories) and day N of M (the per-night accommodation impact already varies by night). Either comes back if the accommodation inputs don't help.

## Consequences
- Prices don't change until a model is trained on nights with event data.
  An all-empty column adds nothing to an EBM's prediction.
- When this lands, every future night is priced again once, since events
  are part of each night's fingerprint (0038).
- Adding inputs to `FEATURES` means retraining saved models.
- Backfills should start inside the plan's 90 days. A window reaching past
  it leaves its oldest month partly unknown, but counted as fetched.
- Nights older than 90 days can't be fetched later, so the forward fetch has to keep running, or that history is lost.
- Nights only become `fetched` through a backfill, so a rolling backfill of the next 90 days has to run regularly, with the routine refresh for changes
  between runs. Nothing schedules it yet.
- Future nights may lack events announced later. Within the 3-month horizon this is mostly small events. The backtest scores past nights, whose lists are complete, so it slightly overstates accuracy on future nights.
- Open question for the backtest: PredictHQ expects guests to arrive before an event; we expect them on the day. The accommodation impact input tests this.
- Every hotel gets the same event inputs; each hotel's model (0009) learns
  which matter for it, so an input that does nothing for one hotel isn't
  removed for all.
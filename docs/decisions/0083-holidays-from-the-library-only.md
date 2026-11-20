# 0083. Every holiday input comes from the `holidays` library; school holidays are dropped

**Status:** Accepted · **Date:** 2026-11-20 · Amends [0032](0032-events-on-a-night-follow-the-model.md),
[0055](0055-events-back-in-the-model.md), [0067](0067-night-before-holiday-input.md)

## Context
Holidays reached the model from two places:

- `is_public_holiday` and `is_school_holiday` came from PredictHQ events
  (0041, 0055). They were empty on nights no events backfill covered, and
  counted a holiday only if PredictHQ had seen it before the night.
- `night_before_holiday` came from the `holidays` library (0067), worked out
  from the date alone, with the weekday off when a holiday falls on a weekend.

So two inputs could disagree about what a holiday is, and one could be unknown
on a night the other knew. The aim is to consolidate where we can. The library
has Ireland's public holidays but no school holidays.

## Decision
- **`is_public_holiday` comes from the library** (`ml/holidays.public_holiday`),
  from the same days off as `night_before_holiday`, weekday-off rule included.
  It's never empty.
- **`is_school_holiday` is dropped.** There's no source for it but PredictHQ.
- **Public and school holiday events are no longer counted** for a night
  (`event._COUNTED`), so they no longer show in a night's events either (0032).
- **Both holiday flags are in the `holidays` input group**; `events` holds only
  attended events.

## Consequences
- **School terms aren't in the model.** If they matter, they'd need a fixed
  list of Irish school terms.
- **Bank-holiday Mondays after a weekend holiday now count as holidays**, as
  they already did for `night_before_holiday`.
- **A night's event list no longer shows holidays.** The explanation names a
  public holiday when it moves the rate.
- **Every model trained before this needs retraining**, which 0079 already
  requires.
- **Holidays are Ireland's for every hotel**, as in 0067.

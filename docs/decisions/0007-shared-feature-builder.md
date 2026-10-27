# 0007. One feature builder for training and serving

**Status:** Accepted · **Date:** 2026-10-13

## Context
If training and serving compute features differently, the model sees inputs at
serving time that don't match what it learned (train/serve skew).

## Decision
`build_features(nights, events, weather, flights)` in
`services/ml/features.py` is the only place features are computed. It's pure:
DataFrames in, DataFrame out; no database access. `FEATURES` fixes the column
order.

Features: `room_type`, `day_of_week`, `month`, `is_public_holiday`,
`is_school_holiday`, `event_count`, `event_attendance`, `event_rank_max`,
`temp_max_c`, `precip_mm`, `wind_kph`, `flight_count`, `avg_fare_eur`.

Rules:
- A multi-day event counts on every night it runs.
- Only categories that bring visitors (`ATTENDED_CATEGORIES`) count toward the
  event features; holidays are separate flags; disasters, delays and the like
  aren't demand.
- Missing weather or flight data stays empty; EBM learns a separate effect for
  unknown values.
- Weather and flights must have at most one row per day, otherwise it raises.

Excluded: `rate` (the target), anything known only after the night (rooms
sold, occupancy, revenue), competitor rates (no data), lead time (no booking
dates), `temp_min_c` and `is_weekend` (redundant).

## Consequences
- Works the same on mock or real data.
- Weather forecasts reach about 14 days ahead and future flight data may not
  exist; those features stay empty for far-out dates until data is backfilled.
- Booking dates are coming from Guestline
  ([0037](0037-three-guestline-reports.md)); "% sold so far" and pickup
  features will be added here when built.
- On mock data, MAE rose from €5.59 to €7.53 versus the mock CSV columns,
  because those included competitor and base rates the mock pricing formula
  uses directly.

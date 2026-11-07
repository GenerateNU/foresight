# 0050. Flights, competitor rates and booking pace are removed

**Status:** Accepted · **Date:** 2026-11-07

Supersedes the booking-pace inputs in
[0049](0049-booking-pace-measured-before-served.md), and the flight columns and
airport codes in [0007](0007-shared-feature-builder.md) and
[0017](0017-cities-are-the-market.md).

## Context
Flights and competitor rates were built but never loaded: no job filled
`flight_arrivals` or `competitor_rates`, so every model trained and served two
flight columns that were always empty. Booking pace (`pct_booked`,
`pickup_7d`) made the backtest worse in 11 of 12 runs (0049), but
`training_data` still rebuilt the booking curves on every training run, and it
needed a second input list (`BACKTEST_INPUTS`) and `--lead-days` to work.

## Decision
- **Flights are gone:** the AeroDataBox, OpenSky and CSO adapters, the
  `flight_arrivals` table, `GET /hotels/{id}/flight-arrivals`, the city airport
  codes, the `XRAPIDAPI_KEY` and `OPENSKY_*` settings, and the `flight_count`
  and `avg_fare_eur` inputs.
- **Competitor rates are gone:** the table and its upsert. There was never a
  source.
- **Booking pace is gone from the model:** `BOOKING_INPUTS`, `BACKTEST_INPUTS`,
  `booking_features`, `bookings_for` and `--lead-days`. `FEATURES` is the one
  input list again. Bookings are still imported and rebuilt
  ([0047](0047-bookings-and-cancellations.md), [0048](0048-rooms-booked-rebuilt-when-asked.md)).
- Migration `53a9a680016f` drops both tables and the airport codes. A downgrade
  recreates them empty.

## Consequences
- Models trained before this have the two flight columns in their stored
  `features`, and the recommendation code no longer builds them. **Retrain
  every hotel** before serving.
- Bringing any of these back means rebuilding the source, table and input
  together. The deleted code is in git history.

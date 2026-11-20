# 0082. Unused pieces are removed: uncertainty, rate basis, booking curves, feedback flags, total rooms

**Status:** Accepted · **Date:** 2026-11-20 · Supersedes [0006](0006-uncertainty-alongside-interval.md),
[0048](0048-rooms-booked-rebuilt-when-asked.md)

## Context
A review of the services and the model found pieces nothing reads, or that
always hold the same value since 0076 and 0079:

- **Uncertainty** (0006): the spread of the EBM's sub-models, stored on every
  snapshot and returned with every recommendation. Nothing showed or used it;
  the 80% interval is the range the manager sees.
- **`rate_basis`**: `nett` or `arr`, to tell booked-room versions from ones
  trained on nights. Since 0076 every version is `nett`, and versions from
  before it are to be deleted.
- **Booking curves** (0048): how many rooms a night had booked on any earlier
  date. Nothing called them; booking pace was dropped from the model (0050),
  and their check against rooms sold went with Actual & Forecast (0080).
- **`rate_replaced` and `weight_factor`** on `pricing_model_feedback`: from
  0044, when feedback replaced a night's rate or reweighted it. Since 0076 a
  manager rate is a row of its own, so every row held the same values.
- **`hotels.total_rooms`**: typed in on create, shown as a label, read by
  nothing else.
- `ingest/files.report_for`: never called.

## Decision
- All of the above is removed. A migration drops
  `recommendation_snapshots.uncertainty`,
  `pricing_model_feedback.rate_replaced`, `pricing_model_feedback.weight_factor`
  and `hotels.total_rooms`.
- The recommendation response loses `uncertainty` and `rate_basis`; every rate
  is before VAT (0076). A hotel's create and update bodies and its response lose
  `total_rooms`, and the top bar shows only the city.
- A model's metrics no longer carry `feedback_rates_replaced`.
- `pricing_model_feedback` keeps `training_rate`: which manager rates each
  version learnt from.

## Consequences
- **A night unlike the training data is no longer flagged** separately from
  its interval. If it's wanted again, the EBM still computes it
  (`predict_with_uncertainty`).
- **How full a night was on an earlier date** would have to be rebuilt from
  the bookings and cancellations again if booking pace comes back.
- **The hotel's size isn't stored anywhere.** Nothing in pricing needs it.

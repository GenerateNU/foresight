# 0079. The model prices one product: DOUBLE, room only

**Status:** Accepted, amended by [0086](0086-remove-unread-fields-and-room-type-routes.md) (no room-type routes) · **Date:** 2026-11-20 · Amends [0056](0056-lead-days-input.md),
[0076](0076-booked-rooms-only-and-manager-rows.md)

## Context
Training (0056, 0076) read every live booking and filed it under the hotel's
single room type, "Standard", which only the Actual & Forecast upload created.
Guestline's room code and rate plan were read and ignored, so one model learnt
a blend of every room type and plan. On Neon (Beresford, 91,813 bookings, live
and priced room-nights):

| Room code | Share | Median nett |
|---|---|---|
| DOUBLE | 49.4% | €134.88 |
| DS | 18.2% | €144.87 |
| DBZ | 17.2% | €134.88 |
| TWIN | 11.4% | €140.26 |
| SINGLE | 3.9% | €121.42 |

DOUBLE leads every year from 2022 to 2027. Within DOUBLE, the rate plan moves
the price more than the room type does: BAR_RO (room only, 59% of DOUBLE's
room-nights) €127.74, BAR_BB (with breakfast) €155.05.

Picking the main product from the data at each training run could change it
between versions, which would confuse the manager.

## Decision
- **The model prices one product, hard-coded:** room code `DOUBLE`, rate plan
  `BAR_RO` (`pricing_model.MAIN_ROOM_CODE`, `MAIN_RATE_PLAN`). Training, the
  backtest and the manager-row weights read only those bookings.
- **Its room type is named after the code** and created by the first training
  run that saves a version. "Standard" is left alone.
- **Each version records its room type** in `pricing_models.room_type_id`; a
  tune-up takes its base's. Serving prices that room type only and refuses any
  other; the tune-up reads only its feedback and snapshots. The unused
  `training_summary` JSON is dropped.
- **`room_type` is no longer a model input**: it never varies.
- **`room_types.room_count` is dropped**: nothing read it.
- The manager's rate is the DOUBLE room-only price, before VAT (0076).

## Consequences
- **Other products aren't priced yet.** Adding them (more room codes or plans,
  or multipliers off the main one) builds on this scaffolding later.
- **The Actual & Forecast upload no longer matters to training**, so removing
  it won't break training.
- **Every existing version stops serving** until a new one is trained: they
  have no room type and read inputs that are no longer built. They're to be
  deleted anyway.
- **Each client hotel must use Guestline's `DOUBLE` and `BAR_RO` codes**, or
  the constants become a per-hotel setting.
- Feedback and snapshots on "Standard" don't carry over. Neon had no feedback
  and 3 snapshots.

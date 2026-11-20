# 0056. Days booked ahead is a model input, trained on booked rooms

**Status:** Accepted · **Date:** 2026-11-19

Revisits the booking-notice question left open by
[0049](0049-booking-pace-measured-before-served.md) and
[0050](0050-drop-flights-and-booking-pace.md), which removed *booking pace*
(rooms already booked at a fixed lead) from a model that trained on one row
per night.

## Context
A guest who books the same week pays less than one who books months ahead:
a typical nett rate of €105 the same day, €138 at 31-60 days and €177 at 181+
days. The model can't see it because a night has many guests who booked at
different times, so there is no single "days ahead" for a night. The input
needs one training row per booked room per night, and the bookings are already
loaded by the upload route ([0052](0052-one-upload-route-and-a-queue-per-hotel.md)).

## Decision
- **`lead_days` is in `FEATURES`.** It's the night minus the day the room was
  booked, never below 0. `build_features` computes it from `booked_on`, so
  training and serving count it the same way; without `booked_on` it's empty.
- **Each version picks its columns from `FEATURES` and stores them.** Booked
  rooms train on every input; nights train on every input but `lead_days`.
  Serving builds every input and keeps the version's stored `features`, so an
  older version gets exactly the columns it trained on.
- **Training rows are booked rooms, one per room per night.**
  `booking.booking_rows` splits each live booking (cancelled ones left out)
  into its nights inside the training window. A booking dated after its night
  (late entries, no-shows) is kept with 0 days ahead. Free or unpriced rooms
  are dropped.
- **The target is `adr_nett`:** the booking's rate per night before VAT, the
  closest to what the guest paid. A stay has one rate, so every night of it
  gets the stay's average: a weekend night in a longer stay is blurred with
  its weekdays. We accept that; there's no per-night price per booking.
- **Only a hotel with one room type trains on bookings.** Bookings carry
  Guestline's codes (DOUBLE, DS, TWIN…), which don't map to room types yet, so
  every booking takes the hotel's single room type. A hotel with more than one,
  or with no bookings in the window, trains on nights as before, with ARR as
  the target. Each version stores which in its metrics as `target`
  (`adr_nett` or `arr`), and recommendations carry it as `rate_basis`
  (`nett` or `arr`).
- **Each booked room weighs 1.** It's a price a guest paid, so the vacancy
  weight ([0003](0003-sample-weighting.md)), which judges a night's listed rate,
  doesn't apply. Busy nights count more because they sold more rooms. Night
  rows keep the vacancy weight.
- **Feedback still judges a night** ([0044](0044-train-on-feedback-given-after-the-night.md)):
  it's weighed against the night's average booked rate and carried onto each
  of its rooms as a ratio, so the gap between early and late bookers stays. A
  version links each piece of feedback once.
- **Identical rows are merged before the fit.** Rooms for one night with the
  same inputs (in practice, booked the same day) become one row: their mean
  rate, weighted by room count. It's the same squared-error fit, and it halves
  Beresford's rows: 352 s became 49 s on data from June 2025, with the same
  scores. Scores and the interval are still per room.
- **The fit holds no database connection.** Training is three steps,
  `prepare_training`, `fit` and `save_version`, and the train job records a
  "fitting" step between the first two, so the worker commits and hands its
  connection back ([0013](0013-one-transaction-per-unit-of-work.md)). The
  backtest loads, closes its session, then fits. Neon drops idle connections,
  and a long fit outlasted one.
- **Counts are rows.** `MIN_TRAINING_ROWS` (120) counts booked rooms or
  nights, whichever the hotel trains on. Metrics and the train job report both
  `training_rows` and `training_nights`, and `holdout_rows` and
  `holdout_nights`.
- **Serving prices a night as if booked today:** `booked_on` is today, so
  `lead_days` is the night minus today. A past night priced again gets 0.
- **The backtest** trains on whatever the training data has. `--inputs
  calendar,events` leaves `lead_days` out, to compare. On booked rooms it
  prints the error by days ahead, and refuses `--baselines`, which compare
  nights.

## Consequences
- **A night's rate changes daily** as its date gets closer, so a version
  trained on bookings reuses a stored snapshot only within the day
  ([0038](0038-recommendations-reused-while-inputs-hold.md)), and stores up
  to one snapshot per viewed night per day. Versions trained on nights don't.
- **Two price bases.** A version trained on bookings recommends nett rates;
  one trained on nights recommends ARR, which runs about 8.5% above nett
  ([guestline data](../guestline-data.md#nett-and-gross)). Their scores can't be
  compared, and neither can a backtest on booked rooms with one on nights.
  Backtests on the same rows with different `--inputs` can.
- **Feedback given on a night-trained version is on the ARR basis,** so a
  manager's rate from then pulls nett training slightly down. `max_rate_change`
  caps it.
- **Scores are per booked room,** so busy nights count more. The interval
  describes one booking's rate, which varies more than a night's average.
- **The holdout can split a night:** the last 15% of rows may cut through a
  night's bookings, so the reported scores are slightly optimistic.
- **Less history.** Rows start where bookings start, and a night near the
  start of the export is missing its long-notice bookings, so train with a
  `start` the export fully covers ([0048](0048-rooms-booked-rebuilt-when-asked.md)).
- **Fits take longer:** 73 s for 36,000 rows, and a full Beresford history is
  several times that. Not yet measured on Render's free plan
  ([0054](0054-hosted-on-render.md)).
- The model copies what the hotel charged, not what was best
  ([0002](0002-predict-rate-in-currency.md)). Part of what `lead_days` learns
  may be *who* books early (groups, negotiated rates), not just *when*.

## First backtest: watch this
On Beresford from June 2025, testing the last 30 nights (3,120 booked rooms,
13 Sep to 12 Oct 2026), `lead_days` made the model **worse**:

| | With `lead_days` | `--inputs calendar,events` |
|---|---|---|
| MAE | €31.50 | €28.44 |
| R² | 0.078 | 0.201 |
| 80% coverage | 84% | 67% |
| MAE, booked 91+ days ahead | €37.83 | €27.90 |

The extra error is almost all on bookings 91+ days ahead. The €105 to €177
gap in Context compares raw rates, with no allowance for season or events, so
much of it may be what month and events already explain. One window isn't
conclusive, so it ships as agreed, and is re-run on longer windows
(`--test-days 90`) as data comes in. If `lead_days` still loses, booked
rooms train without it.

## Follow-ups
- Re-run the backtest with and without `lead_days` on longer windows.
- Price one main room type, and let the manager set the others as multipliers.
  That needs its own decision, and replaces the one-room-type limit.
- Count an event on a booked room only if PredictHQ saw it before the booking
  (0055 counts it from before the night).
- Baselines for booked rooms.
- Cut the holdout on a night boundary.
- Measure a full fit on Render.

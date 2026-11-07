# 0049. Booking pace is measured in the backtest before it's served

**Status:** Superseded by [0050](0050-drop-flights-and-booking-pace.md) · **Date:** 2026-11-02

Revisits the lead-time exclusion in [0007](0007-shared-feature-builder.md).

## Context
[#103](https://github.com/GenerateNU/foresight/issues/103) asks whether how a
night is selling makes the model better. The rebuild
([0048](0048-rooms-booked-rebuilt-when-asked.md)) can say how booked any past
night was on any earlier date, so this can be tested. Serving can't use it yet:
future nights need the daily uploads (#89) and Cancellations exported by
cancellation date ([0037](0037-three-guestline-reports.md)).

## Decision
- **Two inputs, `BOOKING_INPUTS`, kept out of `FEATURES`:**
  - `pct_booked`: rooms booked `lead_days` before the night ÷ the hotel's total
    rooms.
  - `pickup_7d`: rooms gained in the 7 days up to that point.
  `recommendation.py` builds `FEATURES`, so adding them there would hand live
  models empty columns. `train` keeps to `FEATURES`, so nothing served changes.
- **Measured through the backtest.** `training_data` builds them for every night,
  and the `bookings` input group, `--lead-days` and `--start` run them
  ([0042](0042-how-the-backtest-judges-the-model.md)). `BACKTEST_INPUTS` is `FEATURES` plus these.
- **Total rooms, not sellable rooms,** because a future night's rooms out of
  service aren't imported (0037) and training must match serving.
- **One lead time per run, 14 days by default,** so a model still has one row per
  night. That leaves "days until the night" constant, so it isn't an input yet.
- **Nights a hotel's export doesn't cover are left out with `--start`,** not by
  code: 21 Dec 2024 for the first hotel (0048). A night with no bookings stored
  stays empty.

## Results
**Booking pace doesn't go into the model yet.** Mean absolute error in € on the
first hotel, calendar and recorded weather as the base, no events. Each row
averages test windows of 30, 60, 90 and 120 nights. All use nights from
21 Dec 2024, and a set's runs share the same test nights.

| Lead time | Base | + `pct_booked` | + `pickup_7d` | + both |
|---|---|---|---|---|
| 7 days | 23.77 | 22.93 | 24.62 | 24.76 |
| 14 days | 23.77 | 26.26 | 25.11 | 27.66 |
| 30 days | 23.77 | 30.06 | 22.74 | 28.28 |

Adding both inputs made the error worse in 11 of 12 runs. The two small gains,
`pct_booked` at 7 days and `pickup_7d` at 30, don't hold across windows: each is
worse on some of them.

The cause is a change in when guests book. Over the test window's weeks,
`pct_booked` at 14 days fell from 0.85 last year to 0.76, and at 30 days from
0.78 to 0.62, while the average rate hardly moved (€182 to €180). The model
learned that fewer rooms booked means a lower rate, then underpriced nights that
went on to fill at normal rates.

## Consequences
- The rebuild and the inputs stay, so pace can be retested as history grows. Run
  `just backtest <id> --inputs calendar,weather,bookings --start <date>
  --lead-days <n>` beside the same run without `bookings`.
- Pace may help as a comparison rather than a raw number, such as how a night
  stands against the nights around it this year, which a yearly shift wouldn't
  move. That's untested.
- These test windows overlap and cover one autumn, and events weren't in the runs,
  so this is one early reading. It says raw pace isn't safe to serve; it doesn't
  say pace has no value.
- The `FEATURES` split has to end if pace ever ships: `BOOKING_INPUTS` would join
  `FEATURES`, and serving would fill them from the latest upload.

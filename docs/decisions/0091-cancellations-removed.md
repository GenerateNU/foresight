# 0091. Cancellations are no longer read; the retired tables are dropped

**Status:** Accepted · **Date:** 2026-11-26 · Amends [0037](0037-three-guestline-reports.md),
[0047](0047-bookings-and-cancellations.md),
[0052](0052-one-upload-route-and-a-queue-per-hotel.md),
[0080](0080-actual-and-forecast-removed.md),
[0081](0081-weather-removed.md)

## Context
[0047](0047-bookings-and-cancellations.md) stored Guestline's Cancellations
report so that "how full was a night on date D" could be rebuilt, and so that a
booking uploaded as live and cancelled later would drop out. The rebuild went
with booking curves ([0082](0082-dead-code-removed.md)) and booking pace
([0050](0050-drop-flights-and-booking-pace.md)). The only remaining reader was
`list_live_bookings`, which left out bookings whose `book_ref` had a
cancellation.

On Neon that filter removed nothing: none of the 28,454 DOUBLE BAR_RO bookings
the model trains on, and 1 of all 91,813 bookings, had a cancellation. Daily
New Reservations lists only bookings still live when it's exported, so the
backfills never held cancelled rooms. Exporting a second report every day for
that filter isn't worth it.

[0080](0080-actual-and-forecast-removed.md) and
[0081](0081-weather-removed.md) kept `daily_performance` (1,581 nights) and
`weather` (1,494 days) until the team decided. Nothing reads either.

## Decision
- **The Cancellations upload is removed**: its parser, its saver, its entry in
  `bookings/uploads.REPORTS`, its job handler and its model. Uploading one is a
  422, as an unknown report.
- **Training reads every booking** (`booking_repo.list_bookings`); nothing
  checks for a cancellation.
- **`booking_cancellations`, `daily_performance` and `weather` are dropped**,
  with their rows, by one migration. `RETIRED_TABLES` in `migrations/env.py`
  goes with them. A downgrade recreates the tables empty.
- **`JobKind.CANCELLATIONS`, `WEATHER` and `ACTUAL_FORECAST` stay in the
  enum**, so old job rows still load, but nothing queues them. The job rows
  are kept.
- The synthetic `backend/data/Cancellation.csv` and its part in
  `data/generate.py` are removed; `DailyNewReservations.csv` is unchanged.

## Consequences
- **A booking cancelled after its upload stays in training.** With a daily
  7-day upload, a room booked and then cancelled later is counted as a sale at
  the price the guest accepted. It's a real accepted price, so it adds a little
  noise, not a wrong label; most such rows are future nights.
- The manager uploads one report a day instead of two.
- The old cancellations, Actual & Forecast nights and weather days are gone;
  bringing any back means a new upload, a table and a backfill.
- The drop migration must not reach production before the code that stops
  reading `booking_cancellations` deploys: the previous code still maps it,
  and the previous `alembic upgrade head` doesn't know the revision.

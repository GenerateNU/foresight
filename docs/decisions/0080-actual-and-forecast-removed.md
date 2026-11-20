# 0080. Actual & Forecast is no longer read; its table is kept for now

**Status:** Accepted · **Date:** 2026-11-20 · Amends [0037](0037-three-guestline-reports.md),
[0048](0048-rooms-booked-rebuilt-when-asked.md),
[0052](0052-one-upload-route-and-a-queue-per-hotel.md)

## Context
[0037](0037-three-guestline-reports.md) imported three Guestline reports. Since
[0076](0076-booked-rooms-only-and-manager-rows.md) training reads bookings
alone, and since [0079](0079-one-main-room-type-double-room-only.md) the room
type it prices is created by training, not by the Actual & Forecast upload.
Nothing the model, serving or the tune-up does reads Actual & Forecast any more.
Its remaining uses were a listing route, the check of the booking rebuild
against rooms sold, the hotel's first loaded night for backfill windows, and a
freshness entry.

Neon holds 1,581 nights in `daily_performance`. Whether to delete them isn't
decided yet.

## Decision
- **The Actual & Forecast upload is removed**: its adapter, its ingest and its
  entry in `ingest/files.REPORTS`. Uploading one is a 422, as an unknown report.
- **The code that read `daily_performance` is removed**: the model,
  `GET /hotels/{id}/performance`, `list_performance`, `list_nights`,
  `stay_date_range`, `upsert_daily_performance` and
  `booking.check_final_counts`.
- **Windows and weather coverage take the hotel's first and last booked night**
  instead of its first loaded night.
- **Freshness `hotel_data` is the last Daily New Reservations upload.**
- **The table and its rows stay** until the team decides. Alembic ignores the
  table (`RETIRED_TABLES` in `migrations/env.py`), so `alembic check` passes
  without its model. Dropping it is a later migration that also removes it from
  that list.
- **`JobKind.ACTUAL_FORECAST` stays in the enum**, so old job rows still load,
  but nothing queues it. It goes when its job rows are deleted.
- The synthetic `backend/data/Actual & Forecast.csv` and its part in
  `data/generate.py` are removed; the other two files are unchanged.

## Consequences
- **No check of the booking rebuild against rooms sold** (0048). The rebuild
  matched Actual & Forecast on every night from Jan 2025 (0037) when it last
  ran.
- **No capacity per night.** Rooms in stock and out of service came only from
  this report; nothing reads them now.
- Deleting the data needs: the 1,581 nights, the 6 `ACTUAL_FORECAST` job rows,
  and then the enum member and `RETIRED_TABLES` entry.

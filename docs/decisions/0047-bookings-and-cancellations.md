# 0047. Bookings and cancellations are stored as Guestline gives them

**Status:** Accepted · **Date:** 2026-11-01

## Context
[0037](0037-three-guestline-reports.md) chose Daily New Reservations and
Cancellations to show when each night filled up, but left the tables
undesigned. Daily New Reservations lists only bookings still live when it is
exported; cancelled ones are only in Cancellations. Both are uploaded daily
with a 7-day overlap, so the same rows arrive several times.

## Decision
- Two tables, one row per room (`BK…/N`):
  - `bookings`, keyed on hotel + `book_ref`.
  - `booking_cancellations`, keyed on hotel + `cancel_ref`.
  - Refs are only unique within one hotel, so the hotel is part of the key.
- Every load is an upsert on that key ([0018](0018-idempotent-upserts.md)).
  Loading the same file again changes nothing; a changed value updates the row.
- The tables are linked by `book_ref`, not a foreign key: a cancelled booking
  usually has no `bookings` row.
- **A booking is live only if its `book_ref` has no cancellation.** A booking
  uploaded as live can be cancelled days later and arrive in the next
  Cancellations upload. Nothing deletes the `bookings` row, so the ref is then
  in both tables. Its `bookings` row is kept because it holds the room type and
  rate, which Cancellations doesn't.
- Store what we need, as Guestline gives it:
  - Money is nett (gross = nett × 1.135).
  - Times are the hotel's local time ([0023](0023-stay-nights-are-local-dates.md)).
  - The room type is Guestline's code (DOUBLE, TWIN, ...), not a `room_types` row.
- Guest columns are never read: GuestName, Surname, ProfileRef, Operator,
  OperatorCode, CompanyName, AgentName, CancelReason, and Cancellations'
  free-text Company. Daily New Reservations' Company and Agent are codes and
  are kept.
- A bad row (empty reference, unreadable date or amount, departure not after
  arrival, cancelled before booked, wrong number of fields) is skipped and
  counted. A file missing a column we need is rejected.
- Cancellations is expected filtered by cancellation date; the parser assumes
  nothing about arrival dates.

## Consequences
- How full a night was on date D ([0037](0037-three-guestline-reports.md)) is:
  - bookings made by D whose ref has no cancellation, plus
  - cancellations of bookings made by D and cancelled after D.
- An amended booking keeps the dates it had when first uploaded. Daily New
  Reservations shows a booking only on the day it was made, so a later change
  of dates never reaches us.
- A booking cancelled before its first upload is never in `bookings`, so its
  room type and rate are unknown.
- Skipped rows are logged, not stored; the upload result should report the
  count (#89).

Still to confirm:
- Whether `EstimatedRevenue` in Cancellations is nett or gross.

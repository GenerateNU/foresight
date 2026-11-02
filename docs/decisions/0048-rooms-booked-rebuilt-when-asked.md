# 0048. How full a night was is rebuilt when asked

**Status:** Accepted · **Date:** 2026-11-02

## Context
[0037](0037-three-guestline-reports.md) defined how full a night was on an
earlier date, and [0047](0047-bookings-and-cancellations.md) stored the rows.
Still open: whether to compute the count on the fly or store it, and how to
check it against the hotel's final numbers.

The real exports hold 54,683 live bookings and 43,836 cancellations, covering
1,295 nights. Reading them and building every night's count takes about 1.2s.

## Decision
- **Computed on the fly, with no table.** `services/domain/booking.booking_curves`
  reads a range of nights once and returns, for each night, the count after every
  day it changed. `rooms_on` reads a curve at any date. `rooms_booked` is one
  night of the same thing, so the rule lives in one place.
- **A count is for the end of the as-of date.** Dates are compared, not times: a
  booking made at 23:59 on D counts, and a room cancelled at 00:01 on D doesn't.
- **A ref with a cancellation is never live,** matched on the ref alone because a
  cancellation can carry amended stay dates. A ref cancelled twice counts once.
- **The final count is taken the day after the night.** Some bookings and
  cancellations are dated after the stay night (55 and 75 in the real exports).
  As of the night itself, 68 of 658 nights miss by up to 3 rooms; as of the day
  after, none do.
- **`check_final_counts` is given the nights to check.** Which nights the export
  fully covers depends on when a hotel's export starts, so no code holds that date.
  It's a service with no route.

## Consequences
- A stored table would need refreshing after every upload; this has nothing to
  go stale. Each call reads the rows again, so anything needing many nights uses
  `booking_curves` rather than calling `rooms_booked` in a loop.
- The first read straight after a bulk load took 34s, before Postgres had table
  statistics. It settles once autovacuum analyzes the tables.
- From 21 Dec 2024 the rebuild matches rooms sold on all 670 nights. Before that,
  265 of 355 nights run short, so training on them
  ([#103](https://github.com/GenerateNU/foresight/issues/103)) must start later.
- Only the final count can be checked. Counts at earlier dates have no independent
  source, and a booking's date changes never reach us (0047).
- Blocks are 0 on every night so far, so the check doesn't treat them separately.
  A hotel that uses them could show mismatches.

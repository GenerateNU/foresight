# 0031. Guestline reports used for training

**Status:** Superseded by [0037](0037-three-guestline-reports.md) · **Date:** 2026-10-20

## Context
We have full access to the client's PMS, Guestline Rezlynx (Beresford Hotel,
107 rooms). Until now the only import was a nightly Actual & Forecast export
(`daily_performance`), which has no booking dates.

The goal is to tell, for every past night, whether its price was **too low,
about right or too high**, so the model learns from good prices and trusts
bad ones less. [0003](0003-sample-weighting.md) weights nights by final
occupancy, which only catches **too high** (rooms left empty). The client runs
at 93–99% occupancy, so almost every night gets the same weight. An
underpriced night (sold out weeks ahead) looks the same as a well-priced one
(sold out at the last minute). **When** a night filled up is what tells them
apart.

## Decision
Use five reports, all under **Menu → Reports** in Rezlynx.

### Why each report

| Report | What it gives | Why we need it |
|---|---|---|
| **Daily New Reservations** | The date each booking was made | Shows when each night filled up. Sold out weeks ahead means **too low**; sold out in the last days means **about right**. For future nights, "how full now vs similar nights at the same point" is the best early sign of extra demand. |
| **Cancellations** | The date each booking was cancelled | About a third of booked nights are cancelled (4 Oct: 110 booked, 36 cancelled). Without cancellation dates, nights look fuller earlier than they were and good prices get marked too low. |
| **Daily Rate Analysis** | Price and rate plan per booking per night | A night is sold at several prices over the weeks before it. Shows when the rate was raised (e.g. €242 then €299 on one night) and whether bookings kept coming afterwards. |
| **Rate Override** | Bookings where staff set the price by hand | Discounts and fixes aren't market prices. Excluded from training so recommendations don't drift toward them. |
| **Actual & Forecast** | Final rooms sold and revenue per night (already imported), plus **Blocks**, **ROOS** and **Wait List** | Empty rooms on the night mean **too high**. Blocks (group rooms at negotiated prices) are excluded. ROOS (rooms out of service) gives the true number of rooms that could be sold. A waitlist means **too low**. Also checks that the booking rebuild adds up. |

| Question about a past price | Answered by |
|---|---|
| Too high? (rooms left empty) | Actual & Forecast |
| Too low? (sold out early, waitlist) | Daily New Reservations, Cancellations, Actual & Forecast |
| What did guests actually pay? | Daily Rate Analysis |
| Was it a market price at all? | Rate Override, Blocks |

How full a night was on an earlier date D is **rebuilt**: bookings made on
or before D, minus those cancelled on or before D, joined on the booking
reference.

### Key columns

| Report | One row per | Key columns |
|---|---|---|
| Daily New Reservations | booking | BookRef, Booking Date, Arrival, Departure, Nights, Company, Agent, ADR Sold and Reservation Value (Nett/Gross), Cancelled |
| Cancellations | cancellation | Reference, Date, Reason Code, Arrival, Departure, Est. Lost Revenue |
| Daily Rate Analysis | booking × night | BookRef, rate plan and price per night (e.g. `BAR_RO 242.19`) |
| Rate Override | override | BookRef, Applied Date, Arrival, Departure, Rate From/To, Rate Plan, Room Type, Pre/Post Override Gross Total |
| Actual & Forecast | night | Date, Avail, Rooms Sold (Total/Indv/Multi/Blocks), Occ%, Accomm, ARR, APR, Yield, ROOS, DFS, Wait List |

### Exports to collect

| Report | Date range | Filter by |
|---|---|---|
| Daily New Reservations | 2 years back to today | booking date |
| Cancellations | same 2 years | cancellation date |
| Daily Rate Analysis | 2 years back to 3 months ahead | stay date |
| Rate Override | same 2 years | applied date |
| Actual & Forecast | 2 years back to 3 months ahead | stay date; Blocks, Wait List and ROOS on; one row per day |

- CSV where possible; month by month if a report won't run over 2 years.
- The earliest months are partial: some of their bookings were made before
  the range starts.
- Delete guest columns before sharing (Guest Name, Created By, Surname,
  Profile Ref, Operator) but keep BookRef / Reference. Share through a
  private drive, never the repo.
- Record the filter settings used, Nett or Gross, and anything that failed.
- If short on time, start with one past month of Daily New Reservations,
  Cancellations and Actual & Forecast to check the rebuild.

### Not used for now
- **Occupancy** (rooms sold per room type per night): covered by the booking
  reports; revisit when pricing more than one room type.
- **New Reservations by Date**: daily totals not tied to stay nights; only a
  check on import totals.
- **Pickup & Wash**: group blocks only, from Jan 2025, no export.

Room types and room counts are entered at onboarding, not imported (today:
DOUBLE 53, DS 19, DBZ 18, TWIN 13, SINGLE 4).

## Consequences
- Adds the "sold out too early" factor that 0003 left unimplemented, plus a
  waitlist factor. Each needs its own record when built.
- Enables "% sold so far" and "7-day pickup" as features for future nights
  (MVP Q2), computed the same way for training and serving
  ([0007](0007-shared-feature-builder.md)).
- Needs a booking-level table, parsers and a migration; not designed yet.
- Occupancy is computed from sellable rooms (rooms − ROOS). Occ% counts
  out-of-service rooms as unsold, so a fully sold night shows as 99%.
- Nett vs gross must be consistent: gross = nett + 13.5% VAT.
- Parsers drop guest columns; sample exports aren't committed.
- The rebuild misses date changes on amended bookings and may miss group
  blocks; check it against Actual & Forecast before relying on it.

Still to confirm:
- Each report exports as CSV and covers 2 years.
- Daily New Reservations includes bookings that were later cancelled.
- `Date` in Cancellations is the cancellation date.
- What `/1` in BookRef means (room within a multi-room booking?).
- Whether Daily Rate Analysis shows room type, and whether its prices and
  ARR are nett or gross.
- Whether amended bookings keep their original dates (Help → Logs →
  Reservation Logs).
- Where rate-table price changes are logged (Help → Logs → System Logs).
- Whether Actual & Forecast's "Compare with → Custom" shows how full a past
  night was at an earlier date (a ready-made check on the rebuild).
- What DFS means, and whether the current parser's `InStock` column is in
  this export.

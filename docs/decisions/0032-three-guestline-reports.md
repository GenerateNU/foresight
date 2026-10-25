# 0032. Three Guestline reports used for training

**Status:** Accepted · **Date:** 2026-10-25

Supersedes [0031](0031-pms-reports-for-training.md).

## Context
[0031](0031-pms-reports-for-training.md) picked five Rezlynx reports to tell,
for every past night, whether its price was too low, about right or too high.
The client runs at 93–99% occupancy, so final occupancy alone can't tell an
underpriced night (sold out weeks ahead) from a well-priced one (sold out at
the last minute). **When** a night filled up tells them apart.

The first exports have been checked
([guestline-data.md](../guestline-data.md)). The team decided Daily Rate
Analysis and Rate Override aren't needed for the MVP. The one Rate Override
export (200 rows, cut off by a row limit) was mostly automatic OTA discounts,
not prices staff set by hand.

## Decision
Use three reports, all under **Menu → Reports** in Rezlynx.

| Report | What it gives | Why we need it |
|---|---|---|
| **Daily New Reservations** | The date each live booking was made | Shows when each night filled up. Sold out weeks ahead means **too low**; sold out in the last days means **about right**. For future nights, "how full now vs similar nights at the same point" is the best early sign of extra demand. |
| **Cancellations** | The date each cancelled booking was made and cancelled | About a third of booked nights are cancelled. Daily New Reservations leaves cancelled bookings out, so this report is the only record of them. |
| **Actual & Forecast** | Final rooms sold and revenue per night (already imported), plus **Blocks**, **ROOS** and **Wait List** | Empty rooms on the night mean **too high**. Blocks (group rooms at negotiated prices) are excluded. ROOS (rooms out of service) gives the true number of rooms that could be sold. A waitlist means **too low**. Also checks that the booking rebuild adds up. |

How full a night was on an earlier date D is **rebuilt**: live bookings made
on or before D, plus cancelled bookings made on or before D and cancelled
after D. Each room is its own booking: `BK…/N` numbers the rooms within one
reservation.

### Key columns

| Report | One row per | Key columns |
|---|---|---|
| Daily New Reservations | room booked | BookRef, BookingDate, Arrival, Departure, Nights, Company, Agent, ADRSold and ReservationValue (Nett/Gross), RatePlan, MarketSegment, RoomType |
| Cancellations | room cancelled | CancelRef, CancelDate, CancelReasonCode, Ref, ArrivalDate, DepartureDate, EstimatedRevenue, BookingCreatedDate |
| Actual & Forecast | night | Date, Avail, Total, Indv, Multi, Blocks, Occ, Accomm, ARR, APR, Yield, Blked, ROOS, DFS, Waitlist, InStock |

### Exports to collect

| Report | Date range | Filter by |
|---|---|---|
| Daily New Reservations | 2 years back to today | booking date |
| Cancellations | same 2 years | cancellation date |
| Actual & Forecast | 2 years back to 3 months ahead | stay date; Blocks, Wait List and ROOS on; one row per day |

- Delete guest columns before sharing (GuestName, Surname, ProfileRef,
  Operator, OperatorCode, and the free-text CompanyName, Company and
  CancelReason) but keep BookRef, Ref and CancelRef. Share through a private
  drive, never the repo.

### Not used for now
- **Daily Rate Analysis** and **Rate Override**: dropped on 2026-10-25.
- **Occupancy** (rooms sold per room type per night): covered by the booking
  reports; revisit when pricing more than one room type.
- **New Reservations by Date**: daily totals not tied to stay nights; only a
  check on import totals.
- **Pickup & Wash**: group blocks only, from Jan 2025, no export.

Room types and room counts are entered at onboarding, not imported (today:
DOUBLE 53, DS 19, DBZ 18, TWIN 13, SINGLE 4).

## Consequences
- Adds the "sold out too early" factor that [0003](0003-sample-weighting.md)
  left unimplemented, plus a waitlist factor. Each needs its own record when
  built.
- Enables "% sold so far" and "7-day pickup" as features for future nights,
  computed the same way for training and serving
  ([0007](0007-shared-feature-builder.md)).
- Needs a booking-level table, parsers and a migration; not designed yet.
- The rebuild matches Actual & Forecast `Total` on every night from Jan 2025.
  Nights in 2024 are short until about Oct 2024 because their earliest
  bookings predate the export.
- Occupancy is computed from sellable rooms (rooms − ROOS). Occ% counts
  out-of-service rooms as unsold, so a fully sold night shows as 99%.
- The only price per night is the nightly average (`ARR`), not the price
  each booking paid. Overridden or discounted bookings are not marked.
- Nett vs gross must be consistent: gross = nett + 13.5% VAT. `Accomm` in
  Actual & Forecast is 8.5% above the bookings' nett total and 4.3% below
  gross, for reasons not yet known.
- Parsers drop guest columns; sample exports aren't committed.
- The rebuild misses date changes on amended bookings and may miss group
  blocks.

Still to confirm:
- Which reports the manager uploads daily and which once as a backfill.
  The proposal is all three daily, with the first upload covering the
  history.
- Whether amended bookings keep their original dates (Help → Logs →
  Reservation Logs).
- What DFS means, and whether Blocks, Wait List and DFS are always 0 or were
  switched off in the export.
- Why `Accomm` matches neither nett nor gross.
- Whether Actual & Forecast's "Compare with → Custom" shows how full a past
  night was at an earlier date (a ready-made check on the rebuild).

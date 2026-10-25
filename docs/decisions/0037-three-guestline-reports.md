# 0037. Three Guestline reports, uploaded daily

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

### Exports and uploads

All three reports are uploaded daily. The first upload of each is a one-off
backfill of the history.

| Report | Filter by | Backfill (once) | Daily upload |
|---|---|---|---|
| Daily New Reservations | booking date | 2 years back to today | last 7 days |
| Cancellations | cancellation date | 2 years back to today | last 7 days |
| Actual & Forecast | stay date; Blocks, Wait List and ROOS on; one row per day | 2 years back to today | last 7 nights |

- Each daily upload overlaps the last six, so a missed day is filled by the
  next upload. Loading the same rows twice changes nothing.
- Actual & Forecast stops at today. A future night's row only shows rooms
  booked so far, which the booking rebuild already gives, and it would look
  like a finished night with low occupancy.

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
- "% sold so far" for future nights uses total rooms, not rooms − ROOS,
  because future nights' ROOS isn't imported.
- Parsers drop guest columns; real exports aren't committed.
- Daily New Reservations filtered by booking date never shows a booking
  again after it is made. If amendments turn out to be common, add a
  periodic export of future arrivals by arrival date.
- The rebuild misses date changes on amended bookings and may miss group
  blocks.

Still to confirm:
- Whether amended bookings keep their original dates (Help → Logs →
  Reservation Logs).
- What DFS means, and whether Blocks, Wait List and DFS are always 0 or were
  switched off in the export.
- Why `Accomm` matches neither nett nor gross.
- Whether Actual & Forecast's "Compare with → Custom" shows how full a past
  night was at an earlier date (a ready-made check on the rebuild).

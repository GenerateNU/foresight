# Guestline export data

Beresford Hotel exports from Rezlynx, checked on 25 Oct 2026. [0037](decisions/0037-three-guestline-reports.md) lists the reports and why each one matters. This page records what the exports actually contain.

The real exports are not in the repo. `backend/hidden_data/` is gitignored:

- `backend/hidden_data/*.csv` are the raw exports, with guest names.
- `backend/hidden_data/clean/` holds the same four files with guest columns removed.

`backend/data/` is committed and holds synthetic files for tests. They have the real headers, date formats and quoting, for a made-up 10-room hotel over 1 to 14 Sep 2025. Guest columns hold placeholders. Cancelled rooms appear only in `Cancellation.csv`, a few bookings have more than one room, and the live bookings add up to `Total` on every night. Regenerate them with `python3 data/generate.py` from `backend/`.

## Columns removed in `clean/`

| Report | Removed |
|---|---|
| Daily New Reservations | `GuestName`, `OperatorCode`, `CompanyName` |
| Cancellations | `Surname`, `ProfileRef`, `Operator`, `Company`, `CancelReason` |
| Rate Override | `Surname`, `OperatorCode` |
| Actual & Forecast | none |

`CompanyName`, `Company` and `CancelReason` are not on the ticket's list. They are free text that can hold a person's name. The code columns (`Company`, `CancelReasonCode`) and the references (`BookRef`, `Ref`, `CancelRef`) stay.

No field in `clean/` equals a guest name or part of one. The only matches were values such as `DOUBLE` and `Friday`, which also appear in some guest names.

## Coverage

| Report | Rows | Range | Filter (inferred from the data) | Status |
|---|---|---|---|---|
| Daily New Reservations | 55,377 | booked 1 Jan 2024 to 21 Oct 2026 | booking date | Complete for the range |
| Cancellations | 44,026 | arrivals 1 Jan 2024 to 22 Oct 2026 | arrival date, not cancellation date | Usable for past nights |
| Rate Override | 200 | applied 1 to 2 Jan 2024 | applied date | Out of scope. Cut off at 200 rows. |
| Actual & Forecast | 1,025 | 1 Jan 2024 to 21 Oct 2026 | stay date | Complete for the range |
| Daily Rate Analysis | none | | | Out of scope. Not exported. |

Rate Override and Daily Rate Analysis are out of scope. On 25 Oct 2026 the team decided neither is useful. The Rate Override rows already exported stay in `clean/`, but nothing depends on them.

Cancellations lines 32388 and 32869 have the wrong number of fields because a stray quote in a guest name breaks the CSV. Both lines are dropped from `clean/`.

## Answers to the open questions in 0031

**Does each report export as CSV and cover two years?** Daily New Reservations, Cancellations and Actual & Forecast export as CSV and cover 1 Jan 2024 to the export date.

**Does Daily New Reservations include bookings that were later cancelled?** No. None of the 43,834 references in Cancellations appears in Daily New Reservations, and `CancelledTimeStamp` is empty on every row. Cancellations has `BookingCreatedDate`, so the two reports together give every booking. The number of rooms on the books for a night as of date D is the live bookings made by D, plus the cancelled bookings made by D and cancelled after D.

**Is `CancelDate` the cancellation date?** Yes. It is never earlier than `BookingCreatedDate`. 75 rows fall one day after arrival, and 36 of those have reason code `NO_SHOW`.

**What does `/1` in BookRef mean?** It numbers the rooms within one booking. 3,769 bookings have more than one room, and the largest has 45. Within one booking, 1,560 bookings mix room types, 678 mix rate plans, and 2,700 had rooms added at different times, almost all on the same day. Treat each `BK.../N` as its own row.

**Do amended bookings keep their original dates?** Not answered. Each BookRef appears once, so amendments leave no trace in these exports. Check **Help → Logs → Reservation Logs** in Rezlynx.

**What does DFS mean?** Not answered. `DFS`, `Waitlist`, `Blked` and `Blocks` are 0 on every night. Either the export had those options switched off, or the hotel does not use them. `ROOS` varies, and `Avail + Total + ROOS = InStock` (107) on 1,001 of 1,025 nights.

## Nett and gross

- Daily New Reservations has both. `ADRSoldGross / ADRSoldNett` is 1.135 on 96% of rows, which matches 13.5% VAT.
- Actual & Forecast `Accomm` matches neither. From Jan 2025 to Oct 2026, `Accomm` totals €10.33m. Over the same nights, the bookings total €9.52m nett and €10.80m gross. `Accomm` is 8.5% above nett and 4.3% below gross. `ARR` is `Accomm / Total`. `RatePlanRevenue` is 1.5% below the bookings' gross. The cause is unknown.

## The booking rebuild matches Actual & Forecast

Counting live bookings per night reproduces Actual & Forecast `Total` exactly on every night from 1 Jan 2025 to 20 Oct 2026.

In 2024 the count runs short. It is 29 rooms a night short in January and reaches zero by December, because those stays include bookings made before 1 Jan 2024. Treat 2024 nights as complete only from about Oct 2024, or export bookings from mid-2023.

## Pickup for future nights needs cancellations by cancellation date

The current Cancellations export is filtered by arrival date and has only 44 rows for arrivals after the export date. Future-night features ("% sold so far", "7-day pickup") need cancellations of future stays.

## All three reports are uploaded daily

[0037](decisions/0037-three-guestline-reports.md) records the decision. The first upload of each report is a 2-year backfill to today. After that, the manager uploads the last 7 days of each report every day.

## Still open

- Check whether Blocks, Wait List and DFS in Actual & Forecast are always 0 or were switched off in the export.
- Re-export Cancellations by cancellation date.
- Optional: export bookings from mid-2023.
- Find out why `Accomm` sits between nett and gross.
- Check Reservation Logs for amendments and System Logs for rate-table changes.
- Check whether **Compare with → Custom** in Actual & Forecast shows how full a past night was at an earlier date.

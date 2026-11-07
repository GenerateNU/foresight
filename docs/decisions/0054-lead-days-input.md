# 0054. Days booked ahead is a model input, trained on booked rooms

**Status:** Accepted · **Date:** 2026-11-07

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
- `lead_days` (the night's date minus the booking date) is a model input. It
  is not in `FEATURES`: a version has it only if it trained on booked rooms,
  and says so in its stored `features`.
- `booking_rows` builds one row per booked room per night from live bookings
  (cancelled ones are left out). The target is the booking's nett rate
  (`adr_nett`). Rows booked after the night, or free, are dropped.
- `training_data` uses booked rooms when the hotel has bookings in the window,
  and nights as before otherwise. A night's weight (0003) goes onto each of its
  rows. The interval is calibrated by the same two fits, so it now describes
  one booking's rate, which varies more than a night's average.
- Feedback still judges a night: it is weighed against the night's average
  booking rate and applied to each of its rows as a ratio, and a version links
  each piece of feedback once.
- Serving reads the version's own `features`. For a version that has
  `lead_days`, the rate is the price if booked today: the night's date minus
  today, never below 0. A version without it builds the inputs and
  fingerprints it always did. The response shows `lead_days`.
- One room type only. Bookings carry Guestline's codes (DOUBLE, DS, TWIN…),
  which don't map to room types yet, so every booking takes the hotel's single
  room type, and a hotel with more than one is refused.
- The backtest takes whatever the training data has. `--inputs calendar`
  leaves `lead_days` out, to compare. `--baselines` is refused on booked rows.

## Consequences
- **A night's rate changes daily** as its date gets closer, so a stored
  snapshot is reused only within the day
  ([0038](0038-recommendations-reused-while-inputs-hold.md)). Versions
  trained on nights alone don't.
- **Recommendations become nett rates** for a hotel trained on bookings; a
  night-trained version keeps the nightly rate it learned.
- **Less history.** Rows start where bookings start, and a night near the
  start of the export is missing its long-notice bookings, so train with a
  `start` the export fully covers ([0048](0048-rooms-booked-rebuilt-when-asked.md)).
- Training rows are booked rooms, so `nights_used` and the minimum count rows,
  and a fit takes longer (73 s for 36,000 rows).
- The model copies what the hotel charged, not what was best
  ([0002](0002-predict-rate-in-currency.md)).

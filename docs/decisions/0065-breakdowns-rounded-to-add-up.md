# 0065. The calendar card rounds its breakdown so it adds up

**Status:** Accepted · **Date:** 2026-11-19

## Context
A recommendation's explanation is a starting point plus factors, in cents,
and the API makes them add up to the rate exactly ("Smaller effects
combined" absorbs the rounding, see `_explanation` in
`services/domain/recommendation.py`). The calendar's hover card shows whole
euros and rounded each line on its own, so a night could read €180 − €12 +
€7 + €1 + €0 = €176 beside a €175 rate, and small factors showed as a green
"€0". A breakdown that visibly doesn't add up makes a manager doubt all of it.

## Decision
- **Rounding for display happens in the frontend.** Whole euros are a choice
  about this card; the API keeps sending exact cents for anything else that
  reads it (snapshots, reports, the backtest).
- **Sum-preserving rounding:** each factor is rounded to whole euros, and
  what's left over goes to "Smaller effects combined", or the biggest factor
  when the API sent none, so the shown lines add up to the shown rate.
- **Under €1 shows as "+<€1" or "−<€1"** and counts as €0 in the sum. The
  leftover line shows "<€1" too if it ends at 0.
- **At most the 6 largest factors show** (amended 2026-11-26). Real nights
  can have 15, since the model reports pairs like "Friday with December";
  every factor past the sixth is added into "Smaller effects combined" before
  rounding, so the card still adds up. The code is `capFactors`.
- The code is `roundForDisplay` in `features/calendar/calendarUtils.js`.

## Consequences
- The line that takes the leftover can be up to a euro or two off its real
  amount; the real cents are still in the API response.
- Another screen showing a breakdown in whole euros should reuse
  `roundForDisplay` (moving it to `lib/` then) rather than round per line.
- A backend `display_amount` was considered and not chosen: it would put one
  screen's display choice into the API.

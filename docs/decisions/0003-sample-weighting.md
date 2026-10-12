# 0003. Weight training nights by occupancy

**Status:** Accepted · **Date:** 2026-10-13

## Context
Past prices weren't all good prices. A night's price was close to right when
the hotel filled up, but only just in time. Two signs it was wrong:
- **Vacancies on the night** — guests wouldn't pay it (overpriced).
- **Booked too early / sold out early** — guests grabbed it because it was
  cheap (underpriced).

A sample weight sets how much each night's error counts in training. It does
not change the rate; when similar nights had different prices, the model
sides with the higher-weighted ones. Only the ratios between weights matter.

## Decision
`services/ml/weighting.py`:
- `sample_weights = vacancy_factor` (occupancy, 0–1), floored at
  `MIN_WEIGHT = 0.05`. EBM rejects zero weights, and unsold nights should still
  count a little.
- Each signal is its own `*_factor()` function returning 0–1; factors are
  multiplied together. New signals are added the same way.
- Used by training only. Serving never weights (it predicts future nights,
  whose occupancy isn't known).

Rejected:
- **`occupancy × rate / base_rate`** — rewards high prices whether or not they
  sold, biasing predictions upward.
- **Time decay** (older nights count less) — not wanted for now.

## Consequences
- **Booked too early** isn't implemented: `daily_performance` has no booking
  dates. Needs booking-level data or booking-pace snapshots (the client
  export's "cumulative columns" may be this) — a schema and parser change.
- **Competitor signals** (we sold out while they had rooms, and vice versa)
  aren't implemented: there's no competitor data source yet.
- **Waitlist** and **group blocks** exist in the client export but aren't
  mapped yet. Whether group blocks get a low weight or are excluded is open.
- On mock data, weighting barely moves predictions because mock prices are
  formulaic; expect a larger effect on real data.

# 0005. Conformal confidence interval, 80% by default

**Status:** Accepted · **Date:** 2026-10-13

## Context
Each recommendation needs a range the rate is likely to fall in. EBM doesn't
produce prediction intervals itself.

## Decision
Use split-conformal intervals in `EBMModel`:
- `fit` holds out the most recent 15% of rows (`calibration_frac=0.15`) —
  rows must be sorted by time.
- Errors on those held-out rows set the interval width: for an 80% interval,
  the margin is the error size 80% of misses stayed under.
- The level is chosen, not learned. Default 80% (`alpha=0.2`).

## Consequences
- The interval has a real coverage guarantee: on mock data, 78.5% of actual
  rates fell inside the 80% interval (48.6% at 50%, 90.9% at 90%, 96.6% at 95%).
- Higher confidence means a wider, less useful range; 80% balances the two.
- The width is the same for every night; it doesn't flag unusual nights (see
  [0006](0006-uncertainty-alongside-interval.md)).
- The level is hard-coded today; planned to move to a `config.py` setting.

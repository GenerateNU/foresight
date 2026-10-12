# Decision records

One decision per file: what we chose, why, and what it rules out. Read the
relevant record before changing the code it describes. To change a decision,
add a new record that supersedes the old one and update the old record's
status; don't rewrite history.

## Format

```
# NNNN. Title
**Status:** Accepted | Superseded by NNNN · **Date:** YYYY-MM-DD
## Context      — the problem and constraints
## Decision     — what we chose
## Consequences — what follows, including trade-offs
```

Number files sequentially (`0011-short-title.md`) and add them to the index.

## Index

| # | Decision | Area |
|---|---|---|
| [0001](0001-ebm-pricing-model.md) | Explainable Boosting Machine is the pricing model | ML |
| [0002](0002-predict-rate-in-currency.md) | Predict the nightly rate in currency | ML |
| [0003](0003-sample-weighting.md) | Weight training nights by occupancy | ML |
| [0004](0004-exclude-free-nights.md) | Exclude free and staff nights from training | ML |
| [0005](0005-conformal-confidence-interval.md) | Conformal confidence interval, 80% by default | ML |
| [0006](0006-uncertainty-alongside-interval.md) | Report model uncertainty alongside the interval | ML |
| [0007](0007-shared-feature-builder.md) | One feature builder for training and serving | ML |
| [0008](0008-models-stored-in-postgres.md) | Store trained models in Postgres | ML / database |
| [0009](0009-one-model-per-hotel.md) | One model per hotel, one active at a time | ML / database |
| [0010](0010-hotel-airport-codes.md) | Hotels store both IATA and ICAO airport codes | database |
| [0011](0011-pydantic-at-boundaries.md) | Pydantic only at boundaries, named Request/Response | schemas |

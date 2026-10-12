# 0001. Explainable Boosting Machine is the pricing model

**Status:** Accepted · **Date:** 2026-10-13

## Context
We need a model that recommends room rates hotel managers can trust. It has to
explain each recommendation, and it has to let us tell training which past
nights represent good pricing.

## Decision
Use the Explainable Boosting Machine (`ExplainableBoostingRegressor`) from
InterpretML, installed as `interpret-core` (the model without the dashboard
dependencies). It lives in `services/ml/ebm.py` as `EBMModel`, a subclass of
the shared `Model` base.

## Consequences
- Every prediction splits exactly into per-feature contributions plus an
  intercept, including pairwise interactions (e.g. `day_of_week & month`).
  These become the recommendation's explanation.
- `fit` accepts `sample_weight`, which the weighting strategy depends on
  (see [0003](0003-sample-weighting.md)).
- We don't benchmark against the earlier comparison models; the choice is made.
- Version is pinned by `uv.lock`; each stored model records the library
  versions it was trained with (see [0008](0008-models-stored-in-postgres.md)).

# 0008. Store trained models in Postgres

**Status:** Accepted · **Date:** 2026-10-13

## Context
Trained models must be versioned, retrievable by the API, and traceable to
the data and code that produced them.

## Decision
Store each trained model as a row in `pricing_models`
(`database/models/pricing_model.py`): the model serialized with joblib in a
`bytea` column (`artifact`), plus `features`, `metrics`, `lib_versions`,
training window (`data_start`, `data_end`), `version` and `trained_at`.
`EBMModel.to_bytes()` / `from_bytes()` handle serialization; the repository
treats the artifact as opaque bytes.

## Consequences
- No separate file store or model registry to run.
- Pickles can execute code when loaded: only load artifacts our own training
  wrote; never accept a model from outside.
- Pickles can break across library upgrades, hence `lib_versions`.
- Each row is about 17 MB (see [0006](0006-uncertainty-alongside-interval.md));
  every save and load moves that much.

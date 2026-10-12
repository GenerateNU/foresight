# 0009. One model per hotel, one active at a time

**Status:** Accepted · **Date:** 2026-10-13

## Context
Hotels differ in market, room mix and pricing history. Retraining produces new
versions, and serving must know exactly which one to use.

## Decision
- Train one model per hotel. For now we build and test against a single hotel.
- Versions increment per hotel. A new model is saved inactive and becomes
  active only if training succeeds (`repository/pricing_model.activate`).
- At most one active model per hotel, enforced by a partial unique index
  (`uq_pricing_models_active_per_hotel ... WHERE is_active`). `activate`
  deactivates the old model and activates the new one in one transaction.

## Consequences
- A bug can't leave a hotel with two active models; the database rejects it.
- A failed training run leaves the previous model serving.
- Versions are computed as max + 1, so two simultaneous training runs for the
  same hotel would conflict on `(hotel_id, version)`. Run one at a time.

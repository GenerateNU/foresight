# 0004. Exclude free and staff nights from training

**Status:** Accepted · **Date:** 2026-10-13

## Context
Nights sold at a rate of 0 (free or staff rooms) or with no listed rate aren't
sales; they say nothing about pricing.

## Decision
Drop them from training with `training_mask(rate)` in
`services/ml/weighting.py`, rather than giving them a low weight.

## Consequences
- Even a minimum weight would still pull predictions toward €0, so excluding
  them is safer.
- Training must apply the mask **before** building features and weights, so
  features, targets and weights line up row for row.

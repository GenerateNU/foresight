# 0002. Predict the nightly rate in currency

**Status:** Accepted · **Date:** 2026-10-13

## Context
The model could predict the rate directly, demand (occupancy) with a search
over candidate rates, or the rate as a multiple of the room type's base rate.

## Decision
Predict the nightly rate per room type, in currency (EUR).

## Consequences
- Simple to train, serve and explain: contributions are in euros
  ("Concert: +€12").
- Not a multiple of base rate: hotels have no standard base rate to divide by.
- `room_type` is a model feature so the model learns price gaps between types.
- Learning from past prices risks copying past pricing mistakes; sample
  weighting counters that (see [0003](0003-sample-weighting.md)).

# 0053. Room types have no base rate

**Status:** Accepted · **Date:** 2026-11-07

## Context
`room_types.base_rate` held the hotel's stated normal price. It was required
on the Actual & Forecast upload and on room-type create, and shown in
room-type responses. Nothing read it: the model predicts the rate in euros
directly, not as a multiple of a base rate
([0002](0002-predict-rate-in-currency.md)); training weights rejected
`occupancy × rate / base_rate` ([0003](0003-sample-weighting.md)); the
baselines, backtest, recommendations and feedback never used it. The client
prices one standard room and applies its own multipliers downstream.

It was also the one upload input that wasn't a file, which a single upload
route for every report ([0052](0052-one-upload-route-and-a-queue-per-hotel.md))
can't take.

## Decision
- Drop `room_types.base_rate`, and remove it from the upload, room-type
  create and responses, the hotel service and `upsert_room_type`.
- A downgrade adds the column back nullable; the old values are lost.

## Consequences
- A room type is a name and a room count.
- If a reference price is needed later (a floor or ceiling on
  recommendations, "vs your usual price" in the UI), add it back with the
  feature that reads it, and say there why the model doesn't divide by it.

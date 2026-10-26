# 0034. A snapshot is saved only when the model, rate or range changed

**Status:** Accepted · **Date:** 2026-10-26

## Context
Recommendations are saved as snapshots, one row per room type and night, so
a night's rate history can be shown, tied to a manager's feedback, and
checked later. Refreshes run often and most nights don't move, so saving
every answer would fill the table with identical rows. We had to decide how
"unchanged" is judged: same model version and inputs, or same rate.

## Decision
- A new snapshot is saved only when the answer differs from the night's
  latest snapshot in any of `model_id`, `rate`, `interval_low` or
  `interval_high`. Otherwise the night is skipped.
- Inputs aren't compared. A new event or forecast that moves the rate is
  caught because the rate moves; one that doesn't move it isn't worth a row.
  A retrain that gives the same rate still saves a row, so every rate is
  tied to the model that produced it.
- `uncertainty` and the factor breakdown aren't compared; they're recorded
  with the rate, not reasons to save on their own.
- Snapshots are only added, never updated (unlike the upserts in
  [0018](0018-idempotent-upserts.md)). Past nights are never created after
  the fact: reading a past night with no snapshot is a 404.
- A pricing model with snapshots can't be deleted (no cascade on
  `model_id`). Deleting a hotel still removes its snapshots.

## Consequences
- The table grows by the nights that changed, not by every refresh.
- A change only in uncertainty or the explanation isn't recorded; a night
  shows the explanation from when its rate was last saved.
- Pruning old model versions ([0029](0029-every-training-run-is-a-new-version.md))
  must first decide what happens to their snapshots.
- Deleting a room type still removes its history; nothing deletes room types
  today.
- Two refreshes running at the same time could both save the same change;
  nothing prevents that yet.

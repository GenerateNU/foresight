# 0060. The tune-up also learns the nights the manager left alone, as "no change"

**Status:** Accepted, amended by [0062](0062-only-past-nights-are-no-change.md) (past nights only) · **Date:** 2026-11-15 · Amends [0057](0057-daily-tune-up.md)

## Context
[0057](0057-daily-tune-up.md) trains the correction only on nights the manager
priced, each with a gap from the base. With few rates, the correction has no
example of a night that needs nothing, so the average gap goes into its
intercept and shifts every night: three Saturdays raised by €30 raised every
night by about €30. The goal is that nights the manager didn't touch don't
move without a reason.

## Decision
- **Untouched nights join the fit with a gap of 0.** Their target is the base's
  own prediction, so the correction learns "no change here" wherever the
  manager didn't act, and only moves nights that look like the ones they did.
- **Which nights.** Every room type and night with a snapshot (so the manager
  was shown a rate) within `UNTOUCHED_DAYS` (30) of today, back and ahead, that
  has no manager rate, isn't tagged `ONE_OFF`
  ([0058](0058-one-off-nights-teach-the-model-nothing.md)), and whose room
  type the model was trained on (`repository/recommendation.snapshotted_nights`).
- **Weight.** Equal to the manager's nights; no cap yet.
- **Skip rule.** `MIN_TUNE_NIGHTS` still counts manager rates only. A tune-up
  with fewer than 5 manager rates saves nothing, however many untouched nights
  there are.
- **Recorded.** `metrics.untouched_nights` and the job's `untouched_used`.
  `mean_correction` is the correction's mean over the manager's nights only.
  `pricing_model_feedback` still lists only the manager's rates.

## Consequences
- Untouched nights usually outnumber the manager's, so a handful of manager
  rates can be outvoted and the correction can come out small. If it does,
  give untouched nights a lower weight; that needs real data to tune.
- A night the manager accepted and a night they never looked at look the same:
  both are "no change". Accepting is not recorded anywhere.
- Past nights inside the window count too, with the snapshot they had. Nights
  further out than 30 days don't, even if they have snapshots.
- A full retrain doesn't need this: untouched nights already train as recorded
  ([0059](0059-manager-rate-is-the-target-everywhere.md)).

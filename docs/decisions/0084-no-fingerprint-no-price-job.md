# 0084. Snapshots are matched on their stored inputs; prices aren't saved ahead

**Status:** Accepted · **Date:** 2026-11-20 · Amends [0038](0038-recommendations-reused-while-inputs-hold.md),
[0077](0077-scheduled-jobs.md), [0078](0078-tune-up-keeps-what-was-shown-and-points-to-its-base.md)

## Context
[0038](0038-recommendations-reused-while-inputs-hold.md) saves every price
shown as a snapshot and reuses a night's latest one while its inputs hold,
judged by a SHA-256 of the model id and the inputs (`inputs_hash`).
[0077](0077-scheduled-jobs.md) added a `PRICE` job that saved the next 90
nights every day, so the calendar would open already priced.

Measured with 20,000 booked rooms and default model settings, pricing 90 nights
from scratch takes 0.10 s; returning them all from snapshots takes 0.01 s.
Days booked ahead (0056) changes every day for every future night, so a stored
snapshot is reused only within the day it was made.

Snapshots are needed as a record: the feedback verdict and the alignment check
compare against the rate shown, past nights show what they showed, and the
tune-up learns from it (0078). Saving prices ahead isn't.

## Decision
- **A night's latest snapshot is reused when it has the same model and the
  same inputs**, compared directly. The model is deterministic, so that's the
  same price. The hash column goes.
- **Otherwise the night is priced and saved as a new snapshot** (from today on,
  as before). Since days booked ahead are among the inputs, a future night gets
  one new snapshot on each day the calendar shows it. Snapshots are only ever
  added.
- **The `PRICE` job is removed**: its handler, the scheduler's price step, and
  the price after a manual events run. The calendar prices on request.
  `JobKind.PRICE` stays so old job rows load; its migration (0077) stays.
- **A manager row in training and the tune-up is booked on the day the manager
  set the rate** (the feedback's `created_at`), not the day its snapshot was
  made. An untouched night is still booked on the day its latest snapshot was
  shown (0078).

## Consequences
- **Only nights the calendar showed get snapshots.** The tune-up's untouched
  nights are nights the manager was actually shown, not every night priced in
  the background.
- **The first calendar load of a day takes about 0.1 s more** than reading
  saved prices. If that ever matters, reusing a snapshot needs no new
  mechanism: it already is.
- **At most one snapshot per night per day shown**, plus one when a new model
  or new events change it.
- The scheduler runs the events refresh and, with `SCHEDULED_TRAINING`,
  training.

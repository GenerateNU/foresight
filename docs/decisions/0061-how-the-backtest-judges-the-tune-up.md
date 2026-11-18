# 0061. The tuning backtest replays the tune-up after N days of manager rates

**Status:** Accepted, amended by [0062](0062-only-past-nights-are-no-change.md) (past untouched nights, synthetic manager) · **Date:** 2026-11-17

## Context
The daily tune-up ([0057](0057-daily-tune-up.md),
[0060](0060-tune-up-learns-untouched-nights-as-unchanged.md)) serves a
correction with no accuracy check. Nothing said whether it beats the base
model, or how much manager feedback it needs before it does. The base-model
backtest ([0042](0042-how-the-backtest-judges-the-model.md)) can't answer
either.

## Decision
`just tuning-backtest <hotel_id> [--test-days 60] [--sizes 5,10,20,30]`
(`domain/backtest.run_tuning_backtest`). Read-only; every model is in memory.

- **The base goes live at the cutoff.** It trains on every night before the
  newest `test_days` *priced days* (same `_split` and `training_data` as
  `just backtest`, all FEATURES). Counting priced days, not calendar days,
  means the held-out window is always `test_days` days of real data, however
  gappy the hotel's history; `just backtest` still counts calendar days.
- **Recorded rates stand in for the manager's.** For each size N, the nights
  of the first N *priced days* after the cutoff, every room type on them, are
  the manager's feedback. Days are counted among priced days, not calendar
  days, so gaps in the data don't leave a size empty; on complete data the
  two are the same. Sizes with under `MIN_TUNE_NIGHTS` rows are skipped, as
  the tune-up would.
- **Untouched nights as the tune-up sees them.** "Today" is the last feedback
  day. Nights after it, up to `UNTOUCHED_DAYS` ahead, with a room type the
  base trained on, are learned as "no change". Nothing before the cutoff
  counts: snapshots only start when the model goes live. They add only their
  inputs and the base's prediction, never their recorded rate.
- **Two corrections per size:** on the manager's rates only, and with the
  untouched nights (what ships). Both use `tuning.fit_correction`, the
  function `tune` calls, so the backtest scores the tune-up that ships.
- **One scoring window for every size.** The nights after the first
  max(sizes) priced days. The base and every size are scored on the same
  nights, so a row's gain comes from more feedback, not from easier nights.
  The skill is `1 − tuned MAE / base MAE`; above 0, the tune-up helps.

- **It shows which nights it used.** The command prints the base's training
  dates, the scored dates and each size's feedback and untouched dates, and
  saves a plot to `backend/backtest-out/`: date against rate on the scored
  nights, with the actual rate, the base and each shipped tune-up as its own
  line (one panel per room type).

## Consequences
- The feedback is the recorded rate on every night, so it is a manager who
  prices every day. A real manager prices some nights and leaves others
  alone; the backtest is an upper bound on how fast the tune-up learns.
- `--test-days` must be more than max(sizes): the default 60 is 30 days of
  feedback and 30 scored. Larger sizes push the scoring window later.
- The recorded rate is what the hotel charged, not the price before the
  manager acted, so the gap the correction learns is the base's own error.
- One cutoff is one sample, as in 0042; check a narrow gain with other
  `--test-days` values before trusting it.

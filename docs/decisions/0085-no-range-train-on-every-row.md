# 0085. No price range; the served model trains once on every row

**Status:** Accepted · **Date:** 2026-11-24 · Supersedes [0005](0005-conformal-confidence-interval.md),
[0045](0045-refit-on-every-row.md); amends [0069](0069-daily-tune-up.md)

## Context
Each recommendation carried an 80% range (0005): training held out the newest
15% of rows, measured the first fit's errors on them, and served price ± the
error 80% of them fell within. Since 0045 the kept model was a second fit on
every row, so the served model's stored scores and its range came from a
different fit than the one serving.

The range was the same width on every night, so it said nothing about which
nights were uncertain. A tune-up's price moves with its correction but keeps
the base's width, unchecked against anything (it has no rows to measure its
own errors on). The calendar showed it as one line, "Likely range", and nothing
else read it.

Accuracy is what the team needs to measure, and the backtest already measures
it on nights the model hasn't seen, for any window and set of inputs.

## Decision
- **No price range.** The recommendation response, the snapshot and the
  calendar lose it. A migration drops `recommendation_snapshots.interval_low`,
  `interval_high` and `interval_level`.
- **The served model trains once, on every row.** `EBMModel.fit` is one fit;
  the held-out 15%, the first fit and the conformal margin are gone.
- **A version stores no accuracy.** Its metrics hold what it trained on and
  what the fit cost (training rows and nights, feedback and one-off nights,
  mean rate, time and memory). Older versions may still hold holdout scores.
- **Accuracy is measured by the backtest** (`just backtest`, 0042), which keeps
  its own train/test split. A testing suite the team trusts builds on it.
- `ml/base.score` no longer scores coverage.

## Consequences
- **Training does one fit instead of two**, about half the time.
- **A version's quality isn't visible from the API** until a backtest is run.
  Activating a new version is a judgement made from the backtest.
- **The manager sees a price with no range.** If a range comes back, it
  should be per night and checked by the backtest, not one width for all.
- The decision to activate a scheduled retrain (0077) can't look at scores; it
  already didn't.

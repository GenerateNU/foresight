# 0041. The backtest judges the model against baselines and smaller input sets

**Status:** Accepted · **Date:** 2026-11-02

## Context
`just backtest` trains the model on every night up to a cutoff and predicts
the `test_days` after it. Its MAE alone doesn't say whether the model is any
use: a €12 error is good if the obvious guesses are off by €25, and bad if
they're off by €10. Nor does it say which inputs earn their place: an input
that doesn't help adds noise and a line in the manager's explanation
("wind −€2"). [0040](0040-events-in-the-model.md) puts every event input in
the model and asks the backtest to remove the ones that don't help.

## Decision
- **Same data as training.** The backtest loads nights and inputs through
  `pricing_model.training_data`, the loader `train` uses, so it scores the
  model that would ship, events included.
- **Baselines, opt-in with `--baselines`**, in `services/ml/baselines.py`:
  - *Same weekday last year:* the room type's rate 364 days earlier.
  - *Last 4 weeks, same weekday:* the room type's mean rate on that weekday
    over the 4 weeks ending at the cutoff.
  - They see only nights up to the cutoff, as the model does. The 4-week mean
    is anchored at the cutoff, not rolled forward: rolling would use rates
    from inside the test window that weren't known when the forecast was made.
  - They are plain functions, not `Model` subclasses: "last year" needs the
    stay date, which isn't a feature, and baselines are never trained, stored
    or served. They are scored by `ml/base.score`, as `Model.evaluate` is.
  - A night with no history (new room type, or last year's night unpriced per
    [0004](0004-exclude-free-nights.md)) gets no prediction, not a filled one.
    Each baseline is compared with the model on the nights it covers, with a
    skill score `1 − model MAE / baseline MAE`; above 0, the model wins.
- **Input sets.** `ml/features.INPUT_GROUPS` puts every feature in one group:
  calendar, weather, events, flights. The holiday flags are in events: they
  come from PredictHQ and are unknown on the same nights.
  - `--inputs` trains on any mix of groups and single features. To see what
    an input adds, run the backtest with and without it at the same
    `--test-days`; the cutoff, and so the split, is the same.
  - There is no fixed sequence of input sets (an earlier "ladder" was
    dropped): which sets are worth comparing depends on the question, so the
    person running the backtest picks them.
  - Flights have no data, so leave them out.

## Consequences
- An input is worth keeping only if it lowers the error and widens the lead
  over the best baseline, not just if it moves the model's MAE.
- Event history only reaches back about 90 days (0040). With the default
  `--test-days 90`, training has almost no nights with event data and a
  model with event inputs can't learn from them. Use a shorter window, e.g. `--test-days 30`, and treat the events result as an
  early sign: on synthetic data with a strong event effect, 30 training
  nights with events weren't enough to show it.
- With under ~15 months of data, "last year" covers only part of the test
  window; the table says how many nights.
- The 4-week mean gets worse further from the cutoff as the season changes.
  That's intended: it's the guess a manager would make on the cutoff day.
- One cutoff is one sample; a narrow difference should be checked with other
  `--test-days` values before an input is kept or removed.

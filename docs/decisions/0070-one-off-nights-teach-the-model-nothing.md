# 0070. A night tagged one-off teaches the model nothing

**Status:** Accepted · **Date:** 2026-11-16

## Context
[0068](0068-manager-sends-the-rate-they-chose.md) added the `ONE_OFF` reason
tag for a night that won't happen again (a buyout, a private event), but
nothing used it. The daily tune-up ([0069](0069-daily-tune-up.md)) learned
from a one-off rate like any other, and with few rates its correction moves
every night by about the same amount, so one buyout could lift the whole
calendar. A full retrain trained on the night's recorded rate, which is just
as unusual.

## Decision
- **Which nights.** A room type's night is one-off when its current (highest)
  version of feedback ([0043](0043-manager-feedback-is-versioned.md)) carries
  `ONE_OFF`, whether it was given before or after the night. A before-night
  tag means the manager knew it was coming; it describes the night, not a
  forecast. A newer version without the tag makes the night ordinary again.
- **Retrain and backtest.** `domain/pricing_model.training_data` drops one-off
  nights (`feedback_repo.one_off_nights`) after the unpriced ones (0004) and
  before features and weights. The features have no lags, so the other nights'
  inputs don't change. The model's `metrics` gain `one_off_nights`.
- **Tune-up.** `feedback_repo.tuning_feedback` leaves out one-off feedback, so
  its rate isn't learned and doesn't count toward `MIN_TUNE_NIGHTS`. Nor is
  the night used as an untouched "no change" night
  ([0072](0072-tune-up-learns-untouched-nights-as-unchanged.md)).
- `feedback_repo.training_feedback` leaves it out too. The night is dropped
  anyway, so this only keeps the two in step.
- No schema change: tags are VARCHARs, filtered with Postgres `@>`.

## Consequences
- The backtest, sharing `training_data`, neither trains nor scores on one-off
  nights. Its accuracy is measured on nights the model is meant to predict.
- Recommendations for a one-off night are unchanged: the tag only affects what
  the model learns, not what it serves.
- The manager decides what counts as one-off. Tagging ordinary nights would
  hide them from training; nothing checks this.

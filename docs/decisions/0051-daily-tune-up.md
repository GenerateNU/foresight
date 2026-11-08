# 0051. A daily tune-up corrects the active model with the manager's rates

**Status:** Accepted · **Date:** 2026-11-07

## Context
The manager records the rate they chose for a night
([0050](0050-manager-sends-the-rate-they-chose.md)). We want the model to learn
from it every day without a full retrain, and without later nights counting
more just because they were learned from more recently.

## Decision
- **A correction on a frozen base.** `ml/ebm.TunedEBMModel` holds a trained
  `EBMModel` (the base), left as it is, and a small EBM trained with
  `init_score` = the base's predictions, so it learns only the gap. A
  prediction is the base's plus the correction's. The two aren't merged into
  one EBM: `merge_ebms` averages models rather than adding them.
- **It learns only from the manager's rates.** `domain/tuning.tune` takes each
  night's current feedback with a rate, before or after the night
  (`feedback_repo.tuning_feedback`), every one weighted the same. The night's
  inputs are built as recommendations build them, so future nights work.
- **Rebuilt, never stacked.** A tune-up starts from the active model's base:
  if the active model is itself tuned, its base is used and the old correction
  dropped. Every tune-up learns from all current manager rates, so the order
  they arrived in doesn't matter.
- **The correction's settings:** no pairwise terms (its terms are a subset of
  the base's, so `explain` adds them by name and the factor breakdown still
  sums to the rate) and at most 300 boosting rounds. On a handful of rows
  early stopping has almost nothing to judge by, and the library's
  25,000-round limit made a 5-row fit take over a minute.
- **The interval and uncertainty are the base's.**
- **Skipped below `MIN_TUNE_NIGHTS` (5) rates**, saving nothing; the job's
  progress says why.
- **Saved as a new version** (0029), algorithm `ebm-tuned`, served by
  default. `metrics` holds `base_model_id`, `base_version`, `tune_nights`,
  `mean_correction`, and the base's `interval_level` and `interval_margin`.
  `pricing_model_feedback` records the rates used. No migration: the base is
  named in `metrics`.
- **Started by `POST /hotels/{id}/tune`**, a `tune` job (0020). A daily cron
  calls it; the cron itself is outside the app.
- No cap on the correction, no check of how far prices moved, and no accuracy
  check before serving.

## Consequences
- **With few rates, the correction shifts every night by about the same
  amount.** It only sees nights the manager changed, so the average gap goes
  into its intercept and applies everywhere: a manager raising three
  Saturdays by €30 raises every night by about €30. Feeding it nights the
  manager left alone (a gap of 0) would fix this; it was left out on purpose
  for now.
- Nothing stops a bad tune-up from serving. The previous version can be
  activated again by hand (`POST /models/{id}/activate`).
- The cron needs to sign in: the endpoint is behind Google sign-in (0040)
  like every hotel route.
- The base only changes with a full retrain (`POST /hotels/{id}/train`), which
  still uses the 0044 rules, not these. How often to retrain fully is open.
- A tune-up rebuilds the night features and reloads the base each run; both
  are cheap next to a full retrain.

# 0075. The tune-up's correction never sees `month`

**Status:** Reversed for now by [0076](0076-booked-rooms-only-and-manager-rows.md), open for team discussion · **Date:** 2026-11-18 · Amends [0069](0069-daily-tune-up.md)

## Context
The tuning backtest ([0073](0073-how-the-backtest-judges-the-tune-up.md),
[0074](0074-only-past-nights-are-no-change.md)) gave very different results
depending only on where the cutoff fell. Swept over six cutoffs, three manager
shares and several seeds on hotel 1 (synthetic `weekend+15%`), the tune-up beat
the base in 78% of runs, but the worst were −82% and the median at the 90- and
150-day cutoffs was negative. Nights the rule doesn't touch moved by €4 at the
median and up to €25 (the "Drift" column).

Cause: the correction is an EBM fit on a handful of rows (5–30) from a window
of one or two months. `month` is nearly constant there, so the fit learned a
month effect from it, and on later nights, whose months it had never seen, that
term added €12–23 to every weekday. `day_of_week`, the term that carries the
real habit, was the same in training and on the scored nights. Whether a run
failed came down to whether boosting happened to use `month`. L2
regularisation, a lower learning rate and a larger minimum leaf size did not
help: they shrank the real signal along with the spurious one.

## Decision
- **The correction is fit and predicts on every input except `month`**
  (`TunedEBMModel.CORRECTION_EXCLUDED_INPUTS`). The base still sees `month` and
  its predictions are the correction's `init_score`, so the seasonality stays
  in the base.
- **Prediction and `explain` select the correction's columns from the fitted
  EBM** (`feature_names_in_`), not from the setting, so a tuned model stored
  before this change, whose correction has a `month` term, still works.
- Nothing else about the correction changes: no pairwise terms, at most 300
  rounds ([0069](0069-daily-tune-up.md)).

## Consequences
- On hotel 1, `weekend+15%`, 3 seeds, 6 cutoffs, 20 and 30 days of feedback:
  the tune-up beat the base in 45 of 45 runs (was 78%), median skill +35%
  (was +25%), worst +9% (was −82%), worst drift €8.6 (was €25.4). The 90- and
  150-day cutoffs went from −8% and −19% to +40% and +32%.
- Drift is not zero: a median of about €4. A shrink factor of n/(n+10) halves
  it but costs about 14 points of skill, so it isn't applied.
- The correction can no longer learn a manager habit that depends on the time
  of year ("raise rates in August"). The base's own seasonality is untouched,
  and a full retrain still learns month effects.
- Other inputs that are nearly constant in a short window could cause the same
  failure. The event inputs were near zero in these runs; check them when a
  hotel with many events is backtested.
- One hotel, one room type, one synthetic rule. Check the gain on other rules
  and hotels, and with `just alignment` as real manager rates arrive.

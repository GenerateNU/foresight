# 0043. The kept model is refit on every row

**Status:** Accepted · **Date:** 2026-11-02

## Context
[0005](0005-conformal-confidence-interval.md) holds out the newest 15% of rows
to calibrate the interval, and the model kept was the one fit on the other
85%. Event data only reaches back ~90 days
([0041](0041-events-in-the-model.md)), so every row with event inputs fell in
the held-out slice: the model never learned from them and every event input
contributed €0. This lasts until covered nights outnumber the holdout (about
8 months), and the backtest had the same problem.

## Decision
`EBMModel.fit` fits twice:
1. On all but the newest `calibration_frac` of rows. Its errors on the
   held-out rows set the interval margin, as in 0005; its predictions on them
   are kept as `holdout_pred`.
2. On every row. This fit is the model kept and served.

`pricing_model._metrics` scores `holdout_pred`, not the kept model: the kept
model trained on those nights, so its own scores there would look too good.

## Consequences
- The served model learns from the newest nights, where the event data is.
  The backtest gets the same fix, since it trains through `EBMModel`.
- The stored metrics and the interval describe the first fit, not exactly the
  model served. That model has seen more data, so the interval may come out
  slightly wide, which is the safe side.
- Training takes about twice as long (~20 s instead of ~10 s for hotel 1).

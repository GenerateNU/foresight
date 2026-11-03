# 0044. Training uses feedback given after the night: its rate, and a weight

**Status:** Accepted · **Date:** 2026-10-31

## Context
Managers tell us (decision [0043](0043-manager-feedback-is-versioned.md)) when
a night's rate was too high, too low or about right, and sometimes what they'd
charge. If training ignores it, feedback changes what we show but the model
keeps making the same mistakes.

Three ways to use it were open:

1. **Replace** a night's training rate with the manager's.
2. **Weight** nights by the verdict (as [0003](0003-sample-weighting.md) does
   for occupancy).
3. **An input** to the model. Rejected at once: a future night has no feedback
   when it's priced, so serving could never supply it.

The risks: copying the manager's rate teaches the model to copy the manager
rather than learn from what guests paid; there will be little feedback at
first, and a few pieces mustn't swing the model.

## Decision
`services/ml/feedback.py` (`apply_feedback`), called by `train` after the
occupancy weights. Both 1 and 2, on **feedback given after the night** only.

- **Which feedback.** For each room type and night, the current (highest)
  version ([0043](0043-manager-feedback-is-versioned.md)), kept only if its
  `timing` is `AFTER`. Feedback from before a night is never used. If the
  current version is from before the night, an older version from after it
  can't exist, so the night has none.
- **A rate on the right side of the verdict** (too high with a lower rate, too
  low with a higher one): the manager's rate replaces the night's training
  rate, held within 30% of the recorded rate, and the night gets a flat weight
  of 1 (the vacancy weight measured distrust in the old price, which no longer
  applies).
- **A verdict with no rate, or a rate that contradicts it:** the rate stands
  and the night's weight is halved. The rate is known to be off, but not by
  how much.
- **About right:** the rate stands and the night's weight is doubled. A rate
  sent with it is ignored.
- A night with no feedback trains exactly as before.
- **What a model used is recorded.** `pricing_model_feedback` has one row per
  piece of feedback that changed a night: the feedback, whether its rate
  replaced the recorded one, the weight factor, and the rate trained on. The
  model's `metrics` also gain `feedback_nights` and `feedback_rates_replaced`.
  The numbers are `FeedbackSettings` defaults.

## Evidence
Simulated, because the #93 backtest doesn't exist yet and there is no real
feedback. A synthetic hotel (2 room types, 600 training and 120 test nights)
has a latent right rate. Its recorded rates carry 8% noise and underprice event
nights by 25%, the sort of habit feedback should correct. A simulated manager
gives feedback on a share of nights, more often where the rate was wrong,
perceives the right rate within ±8%, and sends a rate 60% of the time when not
"about right". The real `apply_feedback` and `EBMModel` run; error is MAE
against the **right** rate on the 120 unseen nights, mean of 5 seeds. Baseline:
7.83 overall, 48.30 on event nights.

| Nights with feedback | Weight only | Replace only | **Both (chosen)** |
|---|---|---|---|
| 2% | +0.2% | −0.4% | −0.0% |
| 5% | +0.1% | −0.8% | −0.1% |
| 10% | −0.7% | −4.2% | **−3.9%** |
| 25% | −2.4% | −11.7% | **−12.5%** |

(Change in overall MAE; negative is better. Event-night MAE falls 48.3 → 45.0
at 10% and → 40.8 at 25%.)

- **Replacing does nearly all the work.** Weighting alone helps little. Adding
  it to replacing is neutral at 10% and a small gain at 25%, slightly worse at
  2–5%. It is kept because it is the only use for a verdict with no rate, and
  confirms "about right" nights.
- **With little feedback, nothing happens.** At 2–5% the effect is within
  noise, as the ticket asks.
- **The 30% cap matters.** With 20% of manager rates wild (×0.2 or ×2.5): no
  cap is worse than no feedback (+2.5%); caps of 60%, 30% and 15% give −1.9%,
  −2.3% and −1.8%. With 3 wildly wrong rates (×3 the recorded), the biggest
  change to any prediction is 1.2 € capped against 7.4 € uncapped; with 30 such
  rates, 5.2 € against 31.4 €.
- **The weight multipliers barely matter** (about right 1–3, no rate 0.25–1):
  within 0.6 points. A flat weight of 2 for replaced nights did better (−4.8%
  against −3.9%), but it lets each replaced night swing the model twice as
  hard, and the simulated manager's rates are unrealistically accurate, so it
  stays at 1.

**Using before-night feedback did not hurt in the simulation, so it does not
justify excluding it.** Adding feedback from before the night, with the manager
seeing the right rate within ±25%, did a little better than after-night alone
(−5.6% against −3.9%). Anchoring it on the rate already shown made it neutral
(−3.9%, the same). We exclude it anyway, as a decision about risk, not a
result: a before-night view is a forecast with no result to check it against,
and it is often given in answer to our own recommendation, so training on it
would feed the model its own output back. The simulation can't measure that.
Revisit it with real feedback.

## Consequences
- Feedback reaches the model only on the next retrain, and only for nights the
  training window covers.
- Only the current version of a night's feedback is used. Earlier versions
  stay in `feedback` but not in training.
- A manager's rate can pull the model toward their habits. The 30% cap and the
  small numbers bound this; they don't remove it. Accuracy on real nights is
  measured against what guests paid, not the manager's view.
- `PricingModel.metrics` is scored on the newest 15% of training nights, which
  can include replaced rates; those metrics then partly measure agreement with
  the manager.
- A verdict with no rate can only lower a night's weight. It doesn't push the
  model in its direction; only a rate does that.
- The numbers come from a simulation. Rerun it on the #93 backtest and on real
  feedback before trusting them; `FeedbackSettings` is where they change.
- Feedback on a night dropped from training (no or zero rate) is ignored.

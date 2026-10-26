# 0006. Report model uncertainty alongside the interval

**Status:** Accepted · **Date:** 2026-10-13

## Context
EBM trains 14 sub-models (`outer_bags`) and averages them. How much they
disagree measures how familiar a night is to the model. This answers a
different question from the confidence interval:

| | Uncertainty | Confidence interval |
|---|---|---|
| Question | How much should we trust the model on this night? | What range will the rate fall in? |
| Varies per night | Yes — grows on unusual nights | No — same width every night |
| Is a rate range | No | Yes, with a coverage guarantee |

## Decision
Return both. `EBMModel.predict_uncertainty(x)` gives the sub-models' standard
deviation per row; the recommendation response will carry it next to the
interval as a "review this rate" signal.

## Consequences
- The per-bag scores (`bagged_scores_`) must be kept, so a stored model is
  about 17 MB instead of about 3 MB. Lowering `max_bins` can shrink it if
  storage or load time becomes a problem.
- The signal is weak for values beyond the training range: EBM treats them as
  the largest value it saw, so uncertainty rises less than the novelty does.

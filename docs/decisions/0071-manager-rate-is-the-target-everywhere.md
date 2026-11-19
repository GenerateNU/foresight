# 0071. The manager's rate is the target in every retrain and tune-up, and comes back with the recommendation

**Status:** Accepted, amended by [0076](0076-booked-rooms-only-and-manager-rows.md) · **Date:** 2026-11-15 · Supersedes [0044](0044-train-on-feedback-given-after-the-night.md)

## Context
The model's job is to copy how the manager prices, and the manager makes the
final call. [0068](0068-manager-sends-the-rate-they-chose.md) has the manager
send the rate they chose, and [0069](0069-daily-tune-up.md) tunes the model
with it. A full retrain still followed 0044: only feedback given after the
night, a verdict-based weight, and a halved weight when the rate and verdict
disagreed. With the manager now sending a rate before the night, that rule
used almost none of it, and penalised the rest. Nothing returned the
manager's rate with the recommendation, and nothing showed whether the model
was getting closer to the manager.

## Decision
- **One rule for retrain and tune-up.** A night the manager has set a rate for
  trains on that rate, whether it was given before or after the night, at a
  flat weight (`FeedbackSettings.manager_weight`, 1.0). Both use
  `feedback_repo.tuning_feedback`: each night's current version, kept if it has
  a rate. Nights without a manager rate train as recorded, as before.
- **No verdict weights, no cap.** The 0044 weights (×2 about right, ×0.5 wrong
  with no rate) and the 30% cap on the manager's rate are gone. The verdict is
  worked out from the rate (0068), so it adds nothing; and the tune-up never
  capped the rate (0069).
- **`pricing_model_feedback`** still records each rate a version used.
  `feedback_rates_replaced` equals `feedback_nights`.
- **Recommendations carry `manager_rate`.** `GET /hotels/{id}/recommendations`
  returns the rate the manager set for the night (null if none) next to
  `recommended_rate`, so the calendar needs one call. It is read live from
  `feedback`, not stored in the snapshot, so a new rate never starts a new
  snapshot and 0038's reuse is unchanged.
- **Measuring whether the model is getting closer.** Each piece of feedback
  with a rate is compared with the snapshot the manager saw. By the week the
  feedback was given, `GET /hotels/{id}/feedback/alignment` and
  `just alignment <hotel_id>` report the count, the mean gap (manager minus
  model) and the mean absolute gap. A falling mean absolute gap means the
  model is moving toward the manager.

## Consequences
- Retraining on a few manager rates weighs them like any other night and the
  vacancy weights no longer apply to them. A retrain and a tune-up now agree
  on which nights the manager priced.
- Nights the manager left alone: a retrain trains them as recorded, and the
  tune-up learns them as "no change"
  ([0072](0072-tune-up-learns-untouched-nights-as-unchanged.md)).
- The alignment metric uses the recommendation the manager saw, so it measures
  the model at the time of each decision, not how today's model would price
  those nights. It leaves out feedback whose snapshot was deleted.
- The scheduler for the daily tune-up (#137) is not part of this decision.

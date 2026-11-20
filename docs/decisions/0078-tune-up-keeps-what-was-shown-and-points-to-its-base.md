# 0078. Untouched nights keep the rate the manager was shown; a tune-up points to its base

**Status:** Accepted · **Date:** 2026-11-20 · Amends [0069](0069-daily-tune-up.md),
[0072](0072-tune-up-learns-untouched-nights-as-unchanged.md)

## Context
The tune-up (0069) fits a small correction C on top of a frozen base B and
serves B + C. Each tune-up is rebuilt from B on every current manager rate, so
corrections never stack.

Two problems showed up:

- **Untouched nights learned the wrong target.** 0072 taught the correction
  that a night the manager left alone needs no change from B. But once a
  tune-up is active, which is nearly always with a daily tune-up, the manager
  is shown B + C, not B. Leaving a night alone accepts B + C, and learning B
  pulled every accepted correction back toward the bare base at each tune-up.
  The goal is to match the manager, so a night they left alone should keep the
  price they saw.
- **Every tune-up stored a full copy of its base.** A daily tune-up would save
  the same multi-MB base every day.

## Decision
- **An untouched night's target is the rate its latest snapshot showed.** A
  past night in the 30 days before today (0074) with a snapshot, no manager
  rate and no one-off tag joins the correction with that rate. Where the
  manager accepted B + C, the next correction keeps C there; where B alone was
  shown, the gap is 0, as before.
- **A tune-up's artifact holds only its correction.** `pricing_models`
  gets `base_model_id`, the plain version it corrects; null for a full
  training run. Serving and the tune-up load the base's artifact too and join
  the two (`pricing_model.load_model`, `TunedEBMModel.attach_base`). A base
  can't be deleted while a tune-up points to it (`ON DELETE RESTRICT`).
- **A tune-up always corrects a plain base**: the active version, or its
  `base_model_id` if the active version is a tune-up. Corrections still never
  stack.
- **The tuning backtest is unchanged in effect.** Its synthetic manager was
  always shown the base, so its untouched nights pass the base's prediction as
  the shown rate. It is to be redesigned.

## Consequences
- **What the manager accepts sticks.** On a pattern the manager never touches,
  the price stays at what they last accepted, even after a retrain moves the
  base: the untouched nights shown by the old model pull the correction back to
  the old price. That's the intended trade-off for "match the manager". It
  could disagree with prices the manager sets in Guestline instead of the app
  ([open questions](../open-questions.md)).
- **"Left alone" still means "agreed".** A night the manager never looked at
  locks in what it showed, as it locked in B before.
- **A tuned version's artifact is a few KB**, not a copy of the base.
- **A tune-up from before this decision** keeps a full copy of its base in its
  artifact; the migration copies its link from `metrics` into
  `base_model_id`. Old versions are to be deleted before hand-off, so nothing
  else depends on them.

# 0074. Only past nights the manager left alone count as "no change"; the tuning backtest can use a synthetic manager

**Status:** Accepted · **Date:** 2026-11-17 · Amends [0072](0072-tune-up-learns-untouched-nights-as-unchanged.md), [0073](0073-how-the-backtest-judges-the-tune-up.md)

## Context
The tuning backtest ([0073](0073-how-the-backtest-judges-the-tune-up.md)) showed
the tune-up barely moving the base. That had two causes:

- **The test had nothing to learn.** The recorded rate stood in for the
  manager's, so the gap was the base's own error on recent nights: on hotel 1
  it averaged about €1 with a std of €33–37, mostly event spikes. A flat
  correction is the right answer there. It said nothing about whether the
  tune-up learns a habit the base lacks, which is what it's for.
- **Untouched nights cancelled the habit.** 0072 counted nights within 30
  days *either side* of today. The future ones are mostly nights the manager
  hasn't reviewed yet, not nights they agreed with. Against a synthetic
  "weekends +15%" manager, the correction learned 63–99% of the habit without
  them and 14–38% with them; giving them a weight of 0.1 still only reached
  ~32%.

## Decision
- **Only past nights count as untouched.** `domain/tuning._untouched` takes
  nights in the `UNTOUCHED_DAYS` (30) *before* today with a snapshot, no
  manager rate and no one-off tag. A night that already happened and that the
  manager didn't change is one they accepted; a future one may still change.
  The rest of 0072 (target = base's prediction, equal weight) is unchanged.
- **The backtest's untouched nights match.** "Today" is the day after the last
  feedback day. Untouched nights are the feedback days the manager didn't
  review, within `UNTOUCHED_DAYS` back, never nights ahead of today.
- **`--manager-share S`** (default 1): the manager reviews a random share `S`
  of feedback days (seed `MANAGER_SEED`, so runs compare). The other days are
  untouched.
- **`--manager-rule RULE`** (`backtest.ManagerRule`), e.g. `weekend+15%`,
  `events+20%`, `all+10%`. The manager is synthetic: their rate is the base's
  with the rule applied, on feedback and scored nights alike. On a reviewed
  day they set a rate only where the rule changes it and accept the rest, so
  the untouched nights are truly "no change". Nights: `all`, `weekend` (Fri and
  Sat nights), `weekday`, `events` (`big_event_count > 0`; almost every night
  with event data has small events).
- **The table adds `Learned` and `Drift`** for a synthetic manager: the
  shipped correction's mean on the nights the rule matches, over the gap the
  rule adds (100% is all of it), and its mean on the nights it doesn't match
  (€0 is right).

## Consequences
- On hotel 1 (`weekend+15%`, 60 test days), the shipped tune-up now learns
  ~70% of the habit and halves the error. Fit on the manager's rates alone,
  it gets worse than the base (−86%): without untouched nights the weekend
  lift leaks onto every night, so the untouched nights now do their job.
- With recorded rates and a manager who prices every day there are no
  untouched nights, and the correction fits noise: at 30 days, MAE went from
  €23 to €36. Correction settings that hold it back on small data are still
  open; choose them with both modes of this backtest.
- Right after a model goes live there are few past nights, so the early
  tune-ups lean on the manager's rates alone, with 0069's "every night moves"
  effect, until past nights build up.
- A synthetic manager is a test of the mechanism, not of a real hotel. Check
  real gains with `just alignment` as manager rates arrive.

# 0087. Events backfills always walk newest first; the alignment report is removed

**Status:** Accepted · **Date:** 2026-11-24 · Amends [0022](0022-no-retries-resume-instead.md),
[0071](0071-manager-rate-is-the-target-everywhere.md)

## Context
An events backfill took a window three ways: `start` and `end` walked oldest
month first, `start` alone walked from it to today, and `end` alone walked
newest first back to the hotel's first booked night. Only the end-only form
saved the most recent months first, which is what matters when PredictHQ runs
out of credits part-way: recent events drive upcoming prices. Two directions
meant a `backwards` flag, a resume point that was `start` or `end` depending on
it, and two sets of instructions for resuming.

`GET /hotels/{id}/feedback/alignment` and `just alignment` (0071) reported, by
week, how far the manager's rates were from the recommendations they saw.
Nothing in the frontend read it. It measures the model, so it belongs with the
backtest in a testing setup the team trusts, not in the serving API.

## Decision
- **Every events backfill walks newest month first.** `end` defaults to today
  and `start` to the hotel's first booked night; either or both can be given.
  The `backwards` flag goes.
- **`resume_from` is always the `end` to send next**, with the same `start`.
- Old job rows that walked oldest first (`backwards: false`) are still read
  the right way round when working out which nights a backfill covered.
- **The alignment endpoint, CLI command, `just` recipe and query are removed.**
  The measure is listed for the testing setup in the open questions.

## Consequences
- A backfill that stops part-way has always saved the newest months.
- Resuming has one rule.
- Whether the model is getting closer to the manager isn't reported until the
  testing setup includes it.

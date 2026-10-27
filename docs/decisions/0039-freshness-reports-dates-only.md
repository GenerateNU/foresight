# 0039. Freshness reports dates only, recommendations included

**Status:** Accepted · **Date:** 2026-10-27

Supersedes [0033](0033-data-freshness-rules.md).

## Context
0033 had the service judge staleness with fixed limits: events and weather
after 1 day, hotel data after 7, training after 30. Nothing refreshes on a
schedule yet, so those limits were guesses, and a flag computed from them hid
the one thing the manager needs: when the data last refreshed.

0033 also left `recommendations` null until snapshots were stored. Since
[0038](0038-recommendations-reused-while-inputs-hold.md), every recommendation
is stored as it's made, but recommendations aren't a job.

## Decision
- `GET /hotels/{id}/freshness` returns dates, not a judgement. There is no
  `stale` flag; the reader decides whether a date is too old.
- Events, weather, hotel data and training are read from `jobs`, as in 0033:
  - Only routine refreshes count for events (`mode: "recent"`) and weather
    (`mode: "forecast"`). Backfills don't make upcoming rates fresh.
  - Any successful hotel data upload or training run counts.
  - `last_failure` and `error` are set only when the latest attempt failed or
    stopped; a later success clears them.
- `recommendations.last_success` is when the hotel's newest snapshot was saved:
  when a recommended rate last changed. Its `last_failure` and `error` are
  always null, because a failed recommendation stores nothing.

## Consequences
- Changing what counts as too old needs no backend change; it's the reader's
  call.
- Under 0038, a rate whose inputs hold isn't stored again. A hotel with steady
  inputs shows an old `recommendations` date even though its rates are
  current; compare it with the events, weather and training dates.
- A weather backfill that also fetched the forecast still doesn't count as a
  refresh.
- A failure followed by a success no longer shows; the job list still has it.

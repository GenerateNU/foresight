# 0032. Freshness comes from jobs; the service decides what's stale

**Status:** Accepted · **Date:** 2026-10-26

## Context
A manager can't tell whether rates are fresh. If an events refresh or an
upload failed, nothing said so, and the frontend shouldn't encode the rules
for how old each kind of data may get.

## Decision
- `GET /hotels/{id}/freshness` reads the newest finished jobs of each kind;
  there is no new table.
- Only routine refreshes count: events `mode: "recent"`, weather
  `mode: "forecast"`. Backfills don't make upcoming rates fresh. Any
  successful hotel data upload or training run counts.
- Stopped and failed both count as a failed attempt. A failure is shown only
  when it is the latest attempt; a later success clears it.
- Stale: events and weather after 1 day, hotel data after 7, training after
  30. Never succeeding is stale. The rules are constants (`KINDS`) in
  `services/domain/freshness.py`.
- `recommendations` is always null until snapshots are stored (MVP B3); then
  it gets a row in `KINDS`.


## Consequences
- Changing a threshold is a one-line change, with no frontend release.
- A weather backfill that also fetched the forecast doesn't count as a refresh.
- A failure followed by a success no longer shows; the job list still has it.

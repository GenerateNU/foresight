# 0028. Training and recommendations use only ingested data

**Status:** Accepted · **Date:** 2026-10-15

## Context
A recommendation needs weather (and later events and flights) for the night
being priced. The endpoint could fetch what's missing, or rely on ingest
having run.

## Decision
- Training (`POST /hotels/{id}/train`) and recommendations
  (`GET /hotels/{id}/recommendations`) read only what's already saved. Neither
  calls an adapter.
- Missing data isn't fetched: the feature stays empty, which the model learned
  an effect for. The response's `signals` says what was used for the night
  (`recorded`, `forecast`, `typical week N`, `missing`, `not used yet`).
- Weather follows [0024](0024-weather-for-future-nights.md): training uses
  recorded weather only; serving uses recorded, then forecast, then the
  typical weather for that ISO week. Week 53 borrows week 52 when no recorded
  year has one.
- Events and flights are passed empty for now. Their columns stay in
  `FEATURES` so adding them later doesn't change the model's inputs.

## Consequences
- A recommendation is fast and predictable: no outside calls, no quotas.
- Keeping recommendations fresh means running the weather forecast refresh
  (`POST /hotels/{id}/ingest/weather` with no dates) regularly.
- Until events have history, the model can't learn their effect.

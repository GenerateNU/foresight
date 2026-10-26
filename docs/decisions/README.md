# Decision records

One decision per file: what we chose, why, and what it rules out. Read the
relevant record before changing the code it describes. To change a decision,
add a new record that supersedes the old one and update the old record's
status; don't rewrite history.

## Format

```
# NNNN. Title
**Status:** Accepted | Superseded by NNNN · **Date:** YYYY-MM-DD
## Context      — the problem and constraints
## Decision     — what we chose
## Consequences — what follows, including trade-offs
```

Number files sequentially (`0027-short-title.md`) and add them to the index.

## Index

| # | Decision | Area |
|---|---|---|
| [0001](0001-ebm-pricing-model.md) | Explainable Boosting Machine is the pricing model | ML |
| [0002](0002-predict-rate-in-currency.md) | Predict the nightly rate in currency | ML |
| [0003](0003-sample-weighting.md) | Weight training nights by occupancy | ML |
| [0004](0004-exclude-free-nights.md) | Exclude free and staff nights from training | ML |
| [0005](0005-conformal-confidence-interval.md) | Conformal confidence interval, 80% by default | ML |
| [0006](0006-uncertainty-alongside-interval.md) | Report model uncertainty alongside the interval | ML |
| [0007](0007-shared-feature-builder.md) | One feature builder for training and serving | ML |
| [0008](0008-models-stored-in-postgres.md) | Store trained models in Postgres | ML / database |
| [0009](0009-one-model-per-hotel.md) | One model per hotel, one active at a time | ML / database |
| [0010](0010-hotel-airport-codes.md) | ~~Hotels store both IATA and ICAO airport codes~~ (superseded by 0017) | database |
| [0011](0011-pydantic-at-boundaries.md) | ~~Pydantic only at boundaries, named Request/Response~~ (superseded by 0015) | schemas |
| [0012](0012-layered-architecture.md) | Four layers, each calling only the one below | architecture |
| [0013](0013-one-transaction-per-unit-of-work.md) | Only the request and the job runner commit | architecture |
| [0014](0014-services-raise-domain-errors.md) | Services raise domain errors; one place maps them to HTTP | architecture |
| [0015](0015-schemas-in-route-modules.md) | HTTP schemas live in the route that uses them | routes |
| [0016](0016-services-split-by-role.md) | Services are split into domain, adapters, ingest and ml | services |
| [0017](0017-cities-are-the-market.md) | Cities are the market every signal belongs to | data model |
| [0018](0018-idempotent-upserts.md) | Every outside write is an upsert on a natural key | data model |
| [0019](0019-events-merged-across-sources.md) | Events are merged across sources; raw sightings are kept | data model |
| [0020](0020-jobs-in-the-api-process.md) | Long work runs as jobs inside the API, through the API only | jobs |
| [0021](0021-one-ingest-job-per-signal.md) | One ingest job per signal; the dates decide refresh or backfill | jobs |
| [0022](0022-no-retries-resume-instead.md) | No automatic retries; jobs commit per chunk and record where to resume | jobs |
| [0023](0023-stay-nights-are-local-dates.md) | A stay night is a local date in the city's timezone | data model |
| [0024](0024-weather-for-future-nights.md) | Weather for future nights: forecast, then typical weather | ML |
| [0025](0025-migrations.md) | Linear migrations that always roll back | database |
| [0026](0026-no-authentication.md) | The API has no authentication | API |
| [0027](0027-neon-postgres.md) | Postgres is hosted on Neon; pooled for the app, direct for migrations | database |
| [0028](0028-train-and-serve-on-ingested-data.md) | Training and recommendations use only ingested data | ML |
| [0029](0029-every-training-run-is-a-new-version.md) | Every training run is a new, described version | ML |
| [0030](0030-schema-descriptions-and-examples.md) | Every field is described; examples are built from the fields | API |
| [0031](0031-pms-reports-for-training.md) | Guestline reports used for training | data |
| [0032](0032-events-on-a-night-follow-the-model.md) | The events shown for a night follow the model's rule | API |
| [0032](0032-data-freshness-rules.md) | Freshness comes from jobs; the service decides what's stale | API |

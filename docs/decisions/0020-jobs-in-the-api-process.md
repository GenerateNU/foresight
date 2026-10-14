# 0020. Long work runs as jobs inside the API, through the API only

**Status:** Accepted · **Date:** 2026-10-15

## Context
Ingests ran from scripts, outside the API, with no record of what ran or how
far it got. A full backfill can take hours.

## Decision
- There are no scripts. Everything is started through the API.
- Long work is a job:
  - The request validates its input and stores a `jobs` row.
  - It returns 202, and the job runs as a background task in the same
    process.
  - `GET /jobs/{id}` reports its status, progress and resume point.
- Production runs a single uvicorn worker, because jobs live in that process.
- On startup, jobs left queued or running are marked failed.
- One unfinished job per kind per hotel. A second request gets a 409.

## Consequences
- No queue or worker service to deploy.
- A restart kills running jobs. Their saved chunks stay, and they are started
  again by hand.
- Jobs start immediately and run side by side. Running them in order would
  need a worker loop and stored uploads.

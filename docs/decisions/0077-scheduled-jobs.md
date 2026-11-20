# 0077. Routine jobs are scheduled inside the API process

**Status:** Accepted · **Date:** 2026-11-15

## Context
Nothing ran unless someone called the API
([0054](0054-hosted-on-render.md)). Events, retraining and pricing the
coming nights all need to run on their own. Weather isn't scheduled: it's out
of the model ([0055](0055-events-back-in-the-model.md)). PredictHQ only
returns about 90 days, so a missed events refresh can lose data for good.
Every route needs a Google sign-in, and uploads share a per-hotel queue
([0052](0052-one-upload-route-and-a-queue-per-hotel.md)) that lives in the API
process.

## Decision
- **A loop in the API process** (`worker.schedule_forever`), started on
  startup when `SCHEDULER_ENABLED` is set. Every 15 minutes it calls
  `job_service.start_due_jobs`, commits, and enqueues what was queued. It calls
  the same `start_*` functions the routes call and joins the same per-hotel
  queue, so it needs no sign-in and never runs beside an upload.
- **Once a day at a fixed hour.** Each routine job is due at `SCHEDULE_HOUR`
  in the hotel's local time, or 1 hour after a scheduled run failed; one that
  stopped on a quota waits for the next day. Refreshes are expected to run on
  schedule, so only the scheduler's own runs (`params.scheduled`) count: a
  manual run doesn't move the next one, and the hour doesn't drift later by
  each run's length. A deploy, restart or sleep delays a run but never skips
  it; the next check catches it up, and the day after it's back on the hour.
  A routine events refresh starts from the last successful one, manual or
  scheduled, so a gap shorter than PredictHQ's window is filled.
- **The routine, in queue order:** events refresh, training (only with
  `SCHEDULED_TRAINING`), then a `PRICE` job that saves recommendations for
  today and the next 89 nights for each room type the active model covers
  ([0038](0038-recommendations-reused-while-inputs-hold.md)). They're queued in
  the same check, so training learns from the day's events and manager
  feedback ([0044](0044-train-on-feedback-given-after-the-night.md)), and
  pricing reads both the new events and the new model.
- **A manual events run is followed by a `PRICE` job** once it succeeds. New
  events change a night's price without retraining (0055), and a price is
  recalculated when viewed anyway; this saves it ahead so the calendar opens
  without waiting. It doesn't retrain: training is the heaviest job, and a
  day's new events change little of what it learns.
- **A job that can't start is skipped until the next check:** one already
  queued or running, no PredictHQ token, nothing to train on, no active model.
- **A scheduled model goes live**, as a manual one does by default.
- **Off by default.** A local server doesn't call paid APIs by itself.
  `render.yaml` turns the scheduler on and keeps training off.

## Alternatives
- **Render cron jobs calling the API.** They'd need a sign-in besides Google,
  and a separate process can't join the in-memory queue, so a scheduled run
  could overlap an upload. The free plan has no cron jobs.
- **Each job 24 hours after its last run, manual or scheduled.** A manual run
  would move the schedule, the hour would drift later each day by the run's
  length, and pricing could run before the day's training.
- **A fixed hour with no catch-up.** A run missed by a deploy or sleep would
  wait a day.
- **Retraining after a manual events run too.** Costly, and not needed for
  the new events to reach prices.

## Consequences
- On the free plan the loop only runs while the service is awake. The day's
  jobs run at the hour if something keeps it awake, otherwise when the first
  request after the hour wakes it. Training stays off there: 512 MB may not
  fit it, and running out of memory kills the server.
- Events belong to a city, but jobs are per hotel, so two hotels in one city
  fetch the same events twice.
- On a hotel's first day, price waits one check (15 minutes) for the first
  model when `SCHEDULED_TRAINING` is on. With it off, price waits until a
  model is trained by hand.
- On startup, every job left queued or running is marked failed, as before
  this decision. That's right on the free plan, where a deploy, restart or
  sleep stops the old process before the new one starts.
- A failed run is visible in `jobs`, but nothing alerts on it yet.
- New events reach the model's learning once a day, at the scheduled training.

## Moving to a paid plan
The code is written for Render's free plan. A paid plan changes these:

- **Turn on training:** set `SCHEDULED_TRAINING` to `true` in `render.yaml`,
  once training's memory use on real data is known to fit the plan.
- **Overlapping deploys.** A paid plan starts the new instance before stopping
  the old, which keeps running its jobs for up to `maxShutdownDelaySeconds`
  (at most 5 minutes). Failing every unfinished job on startup would then fail
  jobs the old instance is still running. Before upgrading, change startup to
  wait longer than that delay (6 minutes) and then fail only the unfinished
  jobs this process isn't running or holding in its queue, skipping any
  created in the last minute (a job is committed a moment before it joins a
  queue). This was written and checked on a local Postgres in PR #141
  (commit `d3ca3e8`), then taken out because on free it only blocks
  each job kind for 6 minutes after every wake-up.
- **Duplicate jobs during the overlap.** Both instances run the scheduler, and
  the one-unfinished-job-per-kind check reads, then inserts, so two checks at
  the same moment can both queue the same job. Add a partial unique index on
  `jobs (hotel_id, kind)` where status is `QUEUED` or `RUNNING`, for every kind
  but the file kinds, so the database refuses the second.
- **Finish running jobs on deploy:** set `maxShutdownDelaySeconds` to 300 in
  `render.yaml`, so a job running when a deploy stops the old instance has up
  to 5 minutes to finish instead of being cut off and retried.
- **The routine runs on time.** The server no longer sleeps, so the day's jobs
  run at `SCHEDULE_HOUR` instead of when the first request wakes it, and
  saving prices ahead does its job: the calendar opens already priced.

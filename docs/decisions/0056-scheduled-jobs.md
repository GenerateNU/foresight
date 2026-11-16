# 0056. Routine jobs are scheduled inside the API process

**Status:** Accepted · **Date:** 2026-11-15

## Context
Nothing ran unless someone called the API
([0054](0054-hosted-on-render.md)). Events, weather, retraining and pricing
the coming nights all need to run on their own. PredictHQ only returns about
90 days, so a missed events refresh can lose data for good. Every route needs a
Google sign-in, and uploads share a per-hotel queue
([0052](0052-one-upload-route-and-a-queue-per-hotel.md)) that lives in the API
process.

## Decision
- **A loop in the API process** (`worker.schedule_forever`), started on
  startup when `SCHEDULER_ENABLED` is set. Every 15 minutes it calls
  `job_service.start_due_jobs`, commits, and enqueues what was queued. It calls
  the same `start_*` functions the routes call and joins the same per-hotel
  queue, so it needs no sign-in and never runs beside an upload.
- **Due, not timed.** A routine job is due 24 hours after its last run
  succeeded or stopped on a quota, or 1 hour after one failed. A deploy,
  restart or sleep delays a run but never skips it; the next check catches up.
  A routine events refresh already starts from the last success, so a gap
  shorter than PredictHQ's window is filled.
- **The routine, in queue order:** weather forecast, events refresh, training
  (only with `SCHEDULED_TRAINING`), then a `PRICE` job that saves
  recommendations for today and the next 29 nights for each room type the
  active model covers ([0038](0038-recommendations-reused-while-inputs-hold.md)).
  Training before pricing means each day's prices use the newest model.
  Manager feedback reaches the model through training
  ([0044](0044-train-on-feedback-given-after-the-night.md)).
- **A job that can't start is skipped until the next check:** one already
  queued or running, no PredictHQ token, nothing to train on, no active model.
- **A scheduled model goes live only if it's no worse:** the hotel has no
  active model, the active one has no MAE, or the new MAE is at most the active
  one's. Otherwise it's saved but not activated. Manual training is unchanged.
- **Off by default.** A local server doesn't call paid APIs by itself.
  `render.yaml` turns the scheduler on and keeps training off.

## Alternatives
- **Render cron jobs calling the API.** They'd need a sign-in besides Google,
  and a separate process can't join the in-memory queue, so a scheduled run
  could overlap an upload. The free plan has no cron jobs.
- **Fixed clock times.** A run missed by a deploy or sleep would wait a day.

## Consequences
- On the free plan the loop only runs while the service is awake. The day's
  jobs run when the first request wakes it, or on schedule if something keeps
  it awake. Training stays off there: 512 MB may not fit it, and running out
  of memory kills the server.
- Events belong to a city, but jobs are per hotel, so two hotels in one city
  fetch the same events twice.
- On a hotel's first day, price waits one check (15 minutes) for the first
  model.
- MAEs of models trained a day apart are scored on almost, not exactly, the
  same recent nights.
- On a paid plan, a deploy starts the new instance before stopping the old.
  Startup fails every unfinished job, including ones the old instance is still
  running. Fix that before moving to a paid plan.
- A failed run is visible in `jobs`, but nothing alerts on it yet.

# 0056. Routine jobs are scheduled inside the API process

**Status:** Accepted · **Date:** 2026-11-15

## Context
Nothing ran unless someone called the API
([0054](0054-hosted-on-render.md)). Events, retraining and pricing the
coming nights all need to run on their own. Weather isn't scheduled: it's out
of the model ([0055](0055-events-back-in-the-model.md)). PredictHQ only returns about
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
- **Training is the exception: a fixed hour.** It's due once a day at
  `SCHEDULED_TRAINING_HOUR` in the hotel's local time, or 1 hour after a
  scheduled run failed. Only the scheduler's own runs (`params.scheduled`)
  count, so a manual training doesn't move the next one, and the hour doesn't
  drift later by each run's length. A missed hour is caught up at the next
  check; the day after, it's back on the hour.
- **The routine, in queue order:** events refresh, training
  (only with `SCHEDULED_TRAINING`), then a `PRICE` job that saves
  recommendations for today and the next 29 nights for each room type the
  active model covers ([0038](0038-recommendations-reused-while-inputs-hold.md)).
  When both are due in the same check, training is queued first, so pricing
  uses the new model; otherwise price uses whichever model is live. Manager
  feedback reaches the model through training
  ([0044](0044-train-on-feedback-given-after-the-night.md)).
- **A job that can't start is skipped until the next check:** one already
  queued or running, no PredictHQ token, nothing to train on, no active model.
- **A scheduled model goes live**, as a manual one does by default.
- **Off by default.** A local server doesn't call paid APIs by itself.
  `render.yaml` turns the scheduler on and keeps training off.

## Alternatives
- **Render cron jobs calling the API.** They'd need a sign-in besides Google,
  and a separate process can't join the in-memory queue, so a scheduled run
  could overlap an upload. The free plan has no cron jobs.
- **Fixed clock times for every job.** A run missed by a deploy or sleep would
  wait a day. Training uses a fixed hour anyway, but catches a missed one up.
- **Training 24 hours after the last training, like the other jobs.** A
  manual training would move the schedule, and the hour would drift later each
  day by the run's length.

## Consequences
- On the free plan the loop only runs while the service is awake. The day's
  jobs run when the first request wakes it, or on schedule if something keeps
  it awake. Training stays off there: 512 MB may not fit it, and running out
  of memory kills the server.
- Events belong to a city, but jobs are per hotel, so two hotels in one city
  fetch the same events twice.
- On a hotel's first day, price waits one check (15 minutes) for the first
  model when `SCHEDULED_TRAINING` is on. With it off, price waits until a
  model is trained by hand.
- On a paid plan, a deploy starts the new instance before stopping the old. So
  the new one waits 6 minutes, longer than Render's longest shutdown delay,
  then fails only the unfinished jobs it doesn't hold. Until then a job the old
  instance left looks unfinished, and the scheduler skips that kind for a check.
- A failed run is visible in `jobs`, but nothing alerts on it yet.

# 0052. One upload route for every hotel CSV, and a job queue per hotel

**Status:** Accepted · **Date:** 2026-11-07

Supersedes [0020](0020-jobs-in-the-api-process.md) and
[0021](0021-one-ingest-job-per-signal.md).

## Context
The manager uploads three Guestline reports every day
([0037](0037-three-guestline-reports.md)). Only Actual & Forecast had a route
(`/ingest/performance`); bookings and cancellations had parsers but none. A
route per report means a new route for every report we add, and the manager
has to know which route each file belongs to.

The fully dynamic option (building tables from whatever CSV arrives) was
rejected: the model's features are fixed code, so it can't use a column it
doesn't know about. What varies is the source file, not the destination
tables. Column mappings stored as data (one per PMS) were also rejected for
now: Guestline is the only PMS for the foreseeable future.

Jobs ran side by side as soon as they were queued, with a 409 for a second
job of the same kind ([0020](0020-jobs-in-the-api-process.md)). A daily upload
of three files, or a backfill followed by a daily upload, needs files to
stack up and run in order instead.

## Decision

**One route, files recognised by their header**
- `POST /hotels/{id}/ingest/files` takes only files and replaces
  `/ingest/performance`. `/ingest/weather` and `/ingest/events` stay.
- `services/ingest/files.REPORTS` is a fixed list of report kinds. Each has a
  job kind, the columns it needs, a parse function and a save function.
  A file is a kind when its header has all that kind's columns.
- No manual `kind` field. A file matching no kind, or more than one, is a 422.
- Every file is recognised and parsed before anything is queued: one bad file
  is a 422 naming it, and no job is queued.
- At most `UPLOAD_MAX_FILES` (10) files of `UPLOAD_MAX_FILE_MB` (50) each; more
  is a 413.
- Each report has an adapter in `services/adapters/hotel/`.

**One job per file**
- Job kinds per report: `ACTUAL_FORECAST` (was `PERFORMANCE`), `RESERVATIONS`,
  `CANCELLATIONS`. The route returns 202 with one job per file, in upload
  order.
- The job row is the upload record: `params` holds the file name, its sha256,
  rows, rows skipped, and the first and last date the export is filtered by
  (stay date, booking date or cancellation date; 0031).
- A repeated hash is recorded, not blocked: saving is an upsert, so running a
  file twice changes nothing.
- A file job saves 5,000 rows at a time and commits after each chunk;
  `progress` holds rows done and rows total. A file job that ends early is
  finished by uploading the file again.
- No preview or confirmation step, and nothing retrains after an upload.

**One queue per hotel, in memory**
- Every job kind (weather, events, training, files) joins its hotel's queue
  and runs one at a time, first in, first out. Different hotels run side by
  side.
- A job joins the queue in a background task, after the request has committed
  its row. A parsed file waits in memory, keyed by job id, until its job runs.
- A failed job doesn't stop the jobs behind it.
- A second weather, events or training job for a hotel is still a 409 while
  one of the same kind is queued or running. File jobs never are.
- `POST /jobs/{id}/cancel` marks a queued job `cancelled` and drops its parsed
  file. A running or finished job is a 409. A job no longer `queued` when its
  turn comes is skipped.
- Still from 0020: long work is a job, started through the API only, inside
  the API process, so production runs a single uvicorn worker. A restart loses
  the queues: on startup every queued or running job is marked failed.

## Consequences
- Adding a report is one adapter and one entry in `REPORTS`, with no new
  route. A second PMS would need mappings as data; revisit then.
- Reservations and cancellations can now be uploaded.
- A long backfill (events, a 2-year upload) holds up everything queued behind
  it for that hotel, including training. Cancel a wrong one while it's queued.
- Uploaded files are never stored; the hash only tells a repeat apart.
- Parsed files held in memory until they run are bounded by the upload limits
  times the number of uploads waiting.
- Freshness ignores cancelled jobs: they never ran.

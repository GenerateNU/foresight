# Foresight backend: system design

How the backend fits together: the layers, the patterns each one uses, and how
a request or a job moves through them. Written from the code as of 2026-11-07.
The reasons behind each choice are in
[`decisions/`](decisions/README.md); this document links to them rather than
repeating them.

---

## 1. The system in one page

Foresight stores a hotel's nightly sales history and the outside signals that
move demand (events), so a pricing model can recommend a
nightly rate.

```
                    ┌──────────────────────────────────────────────┐
  HTTP client ────▶ │ routes     HTTP only: parse, call, map        │
                    └──────────────┬───────────────────────────────┘
                                   │ plain arguments in, domain objects out
                    ┌──────────────▼───────────────────────────────┐
  worker.py ──────▶ │ services                                      │
  (jobs, schedule)  │   domain/    rules and reads per domain       │
                    │   ingest/    fetch + save, in chunks          │
                    │   adapters/  outside APIs and files, no DB    │──▶ outside APIs
                    │   job.py     job kinds + lifecycle            │
                    │   ml/        pricing model (EBM)              │
                    └──────────────┬───────────────────────────────┘
                                   │ plain values in, ORM objects out
                    ┌──────────────▼───────────────────────────────┐
                    │ repository  the only code that queries        │
                    └──────────────┬───────────────────────────────┘
                    ┌──────────────▼───────────────────────────────┐
                    │ database    models, enums, session, Alembic   │──▶ Postgres
                    └──────────────────────────────────────────────┘
```

Two kinds of work enter the system:

- **Requests** (reads, creates, updates). One request is one database
  transaction, committed before the response is sent.
- **Jobs** (ingesting events and bookings, training, tune-ups). The request
  validates the input, stores a job and returns `202` at once. The job runs in
  the background in the same process and commits after every chunk.

Everything is async: FastAPI handlers, SQLAlchemy sessions and every outside
HTTP call. People sign in with Google ([0040](decisions/0040-google-sign-in-cookie-sessions.md)),
every route but `/health` and `/auth/*` needs a signed-in user, and a hotel is
reachable only by a user linked to it.

---

## 2. Layers and the rules between them

A layer calls only the layer directly below it
([0012](decisions/0012-layered-architecture.md)).

| Layer | Folder | Owns | Must not |
|---|---|---|---|
| routes | `routes/`, `main.py` | URLs, status codes, request/response schemas | query, hold business rules, catch domain errors |
| services | `services/` | business rules, orchestration, outside APIs, the model | know about HTTP, see schemas, commit |
| repository | `repository/` | every query and write | commit, hold business rules |
| database | `database/` | tables, enums, constraints, migrations, session | query |

Actual imports:

```
routes      → services, database.enums, database.models.user (the signed-in
              user's type), worker (to schedule a job)
services    → repository, database.models/enums, config (job.py, domain/user.py)
repository  → database
worker      → services.job, database.session
```

Enums live in `database/enums.py` because columns use them; every layer may
import them.

### 2.1 File layout

One file per domain, singular, with the same name in each layer. Outside
signals are grouped under `signals/` in both the database and the repository.

```
backend/foresight/
  main.py                  app, routers, session and CORS middleware, error handlers, lifespan
  config.py                settings (pydantic-settings)
  worker.py                runs jobs; commits per chunk
  cli.py                   operator commands (`just link-user`, `just backtest`); commits once per command
  routes/
    helpers.py             SessionDep, schema bases, PageResponse, paginate
    errors.py              domain error → status code
    city.py hotel.py event.py ingest.py job.py
    model.py feedback.py health.py
    auth.py                Google sign-in, logout, /auth/me
    access.py              CurrentUserDep
  services/
    errors.py              NotFound / Conflict / InvalidRequest / NotConfigured /
                           NotSignedIn / Forbidden
    job.py                 starting jobs and their lifecycle
    handlers.py            what each kind of job does once it runs
    scheduler.py           the daily routine
    domain/                booking, city, hotel, user, event, normalize, window,
                           model, training_data, tuning, backtest,
                           recommendation, explanation, feedback, freshness
    ingest/                event; files (report kinds, header recognition),
                           bookings
    adapters/              predicthq
      hotel/               one per CSV report: reservations, cancellations;
                           common (shared reading)
    ml/                    ebm, features, holidays, baselines, resources
  repository/
    upsert.py pagination.py
    booking.py city.py hotel.py job.py model.py recommendation.py feedback.py
    user.py
    signals/               event
  database/
    base.py enums.py session.py
    models/                booking, city, hotel, job, pricing_model, recommendation, feedback,
                           user
      signals/             event
    migrations/
```

`city.py` in each layer is a small, complete slice to copy when adding a
domain.

---

## 3. Patterns that span every layer

### 3.1 Transactions

Only two places commit ([0013](decisions/0013-one-transaction-per-unit-of-work.md)):

| Caller | Session from | Commits |
|---|---|---|
| HTTP request | `database/session.get_session` | once, after the handler; rolls back on any error |
| job | `worker.run_job` | after every chunk, then once for the final status |

Repositories flush when they need a generated id. `update_hotel` and
`update_city` run in a savepoint, so a rename that hits a unique constraint
fails on its own and the request can still answer 409.

### 3.2 Errors

Services raise; `routes/errors.py` maps
([0014](decisions/0014-services-raise-domain-errors.md)).

```
services/errors.py                     routes/errors.py
DomainError
 ├─ NotFoundError         ─────────▶   404
 ├─ ConflictError         ─────────▶   409
 ├─ InvalidRequestError   ─────────▶   422
 │   └─ InvalidWindowError  (services/domain/window.py)
 ├─ NotConfiguredError    ─────────▶   503   (an API key or secret isn't set)
 ├─ NotSignedInError      ─────────▶   401   (no valid session)
 └─ ForbiddenError        ─────────▶   403   (known, but not allowed)
```

- Every `get_x(id)` in a service raises `NotFoundError`; nothing returns None
  to a route.
- A service function that takes a `hotel_id` loads the hotel first, so an
  unknown hotel is a 404 before anything else runs.
- The repository returns None for a missing row or a duplicate insert. The
  service decides that it is an error.
- Every error body is `{"detail": "..."}`.
- Adapter errors (`OutOfCreditsError`, `RateLimitedError`, ...) never reach
  HTTP. They end a job as `stopped` or `failed` (section 5).
- A failed Google callback (bad state, Google refused, bad ID token) is a 400
  raised in `routes/auth.py`: it comes from the OAuth library, not a service.

### 3.3 Naming

| Verb | Returns |
|---|---|
| `get_x(id)` | the row; the service raises `NotFoundError` if missing |
| `list_x(...)` | rows, or `(rows, total)` when paginated |
| `create_x` | the new row; a duplicate becomes `ConflictError` |
| `update_x` | partial update; only the fields given |
| `upsert_x` | idempotent write; returns new/updated/unchanged counts |

Constraints and indexes are named by the convention on `Base.metadata`:
`pk_<table>`, `uq_<table>_<cols>`, `fk_<table>_<col>_<ref>`,
`ix_<table>_<cols>`. Upserts target constraints by these names.

### 3.4 Data types

| Kind | Type |
|---|---|
| money | `Numeric(10, 2)` ↔ `Decimal` |
| a night (stay, event date, arrival day) | `Date`, local to the city ([0023](decisions/0023-stay-nights-are-local-dates.md)) |
| an instant | `DateTime(timezone=True)` |
| enums | VARCHAR holding the member name; adding a member needs no migration |
| raw source payloads | `JSONB`, kept verbatim |

### 3.5 Idempotent writes

Every write from an outside source or a file is an upsert on a natural key
([0018](decisions/0018-idempotent-upserts.md)):

| Table | Natural key |
|---|---|
| `bookings` | hotel_id, book_ref |
| `booking_cancellations` | hotel_id, cancel_ref |
| `room_types` (CSV import) | hotel_id, name |
| `events` | dedupe_key (normalized title + city + local start date) |
| `event_observations` | source, source_ref |

`repository/upsert.py:upsert_rows` is the shared bulk upsert. It rewrites a
row only when a value changed, reports `NEW / UPDATED / UNCHANGED` counts,
batches under Postgres's parameter limit and collapses duplicate keys in a
batch. Each source keeps its own row; choosing between sources happens when
the model reads the data.

### 3.6 Schemas and pagination

HTTP schemas live in the route module that uses them
([0015](decisions/0015-schemas-in-route-modules.md)):

- `RequestSchema` rejects unknown fields; `ResponseSchema` builds from an ORM
  object or a dataclass. Both are in `routes/helpers.py`.
- Constraints and descriptions go in `Field(...)`, so they are enforced and
  shown in `/docs`. Every field, path id and query parameter has a
  description; units, inclusive dates, currency and what `null` means go there
  ([0030](decisions/0030-schema-descriptions-and-examples.md)).
- Example values go in `examples=`, as neutral placeholders. A field with a
  default shows its default instead. The body `/docs` shows is built from the
  fields (`example_body` in `routes/helpers.py`), never written by hand.
- A PATCH body reuses its create body's field settings; each module keeps its
  own "cannot be null" check and its own `start`/`end` parameters.
- PATCH bodies use `model_dump(exclude_unset=True)`: omitted fields are left
  alone, `null` clears an optional field and is a 422 on a required one.
- A schema class has a one-line docstring and no `Attributes:`; its fields'
  descriptions document it. An endpoint's docstring puts `Args:`/`Returns:`/
  `Raises:` after a form feed (`\f`), so `/docs` shows only the summary
  ([0088](decisions/0088-one-docstring-style.md)).

Lists that grow without bound take `?limit=&offset=` (default 50, max 200) and
return `{"items", "total", "limit", "offset"}`: events,
and jobs. Cities, hotels and room types return a plain list.

### 3.7 Outside HTTP

Adapters make each request once and raise on failure; there are no automatic
retries ([0022](decisions/0022-no-retries-resume-instead.md)). Each adapter
turns its source's quota responses into a named error:

| Source | Quota error |
|---|---|
| PredictHQ | 402/403 → `OutOfCreditsError`; 429 → `RateLimitedError` |

---

## 4. Data model

```
cities ─┬─< hotels ─┬─< room_types                       (DOUBLE, the one the model prices; 0079)
        │           ├─< bookings                          (rooms booked, still live; 0047)
        │           ├─< booking_cancellations             (rooms cancelled; linked by book_ref)
        │           ├─< pricing_models                    (trained models; one active;
        │           │                                      a tune-up points to its base, 0078)
        │           ├─< recommendation_snapshots          (every rate recommended; 0038)
        │           ├─< feedback (also > room_types)      (the manager's view of a night; 0043)
        │           └─< jobs                              (ingest runs)
        │
        └─< events ─< event_observations                    outside signals,
                                                            shared by every hotel
                                                            in the city

users ─< user_hotels >─ hotels                              (who works for which hotel)
users ─< feedback >─ recommendation_snapshots               (who said it; the rate they saw)
```

**Cities are the market** ([0017](decisions/0017-cities-are-the-market.md)).
A city holds its name, a unique normalized slug, country, IANA timezone,
and centre coordinates. Events are searched at the
centre; "today" for a job is today in the city's timezone. A
hotel keeps its own coordinates for distance to venues.

**Users** ([0035](decisions/0035-users-keyed-on-google-id.md)) are Google
accounts, identified by Google's account id and never by email (`users.email`
is not unique). `user_hotels` links a user to a hotel, keyed on the pair so
linking twice changes nothing; a hotel can have several users, a user can
belong to several hotels, and a user with none is valid. Signing in with Google
creates the user, or refreshes the existing one's email, name and
`last_signed_in_at` ([0040](decisions/0040-google-sign-in-cookie-sessions.md)).
Creating a hotel links its creator, and any member can link a colleague with
`POST /hotels/{id}/users`.
A hotel is reachable only through its link.

**Feedback** ([0043](decisions/0043-manager-feedback-is-versioned.md),
[0068](decisions/0068-manager-sends-the-rate-they-chose.md)) is the rate the
manager chose for a night, sent only when they change ours, with an optional
reason as tags from a fixed list, free text, or both. It names the snapshot the
manager saw. Rows are only added; a change is the next `version` for that room
type and night, the highest is current, and earlier ones keep their times. It
records who gave it (null for feedback saved before sign-in was required).
Whether ours was too high or too low, and whether it came before or after the
night, aren't stored: they follow from the rates and dates
([0086](decisions/0086-remove-unread-fields-and-room-type-routes.md)).

**Foreign keys** always state `ON DELETE`:

- `CASCADE` from a city to its signals, and from a hotel to its room types,
  nights, pricing models, jobs, recommendation snapshots and feedback, from a
  room type to its feedback, and from a user or a hotel to its `user_hotels`
  links.
- `RESTRICT` from a hotel to its city: a city with hotels can't be deleted.
- `NO ACTION` from a snapshot to its pricing model: a model with snapshots
  can't be deleted, but deleting the hotel removes both
  ([0038](decisions/0038-recommendations-reused-while-inputs-hold.md)).
- `SET NULL` from an observation to its event, so raw sightings survive, and
  from feedback to its snapshot and its user, so what the manager said survives.

**Relationships are `lazy="raise"`.** An unloaded relationship fails at once
rather than at some later point in async code. The hotel repository always
loads `Hotel.city` with a join, because almost every service needs it.

**Events** ([0019](decisions/0019-events-merged-across-sources.md)): `events`
holds one merged row per real-world event; `event_observations` keeps each
source's raw record. `services/domain/event.save_event`:

1. Looks the sighting up by the source's own id first, then by dedupe key. A
   revised start date changes the key, so looking up by key first would orphan
   the old row.
2. Merges two rows if a revision moves onto a key another event holds.
3. Ranks every sighting of the event (structured over extracted, live over
   withdrawn, newest revision, then source_ref) and writes the winner's values.
4. Records the sighting.

**Migrations** ([0025](decisions/0025-migrations.md)) are linear, explain why
they exist, and always roll back. CI checks for one head, runs `alembic check`
and does a full downgrade and upgrade.

---

## 5. Jobs

Long work runs as jobs inside the API process, one kind per signal or
uploaded report, through one queue per hotel
([0052](decisions/0052-one-upload-route-and-a-queue-per-hotel.md)).

### 5.1 Kinds

| `POST /hotels/{id}/ingest/…` | Kind | No dates | With dates | Chunk |
|---|---|---|---|---|
| `events` | `EVENTS` | events PredictHQ revised since the last refresh (7 days the first time) | every event active in the window | one month |
| `files` (multipart) | one per file: `RESERVATIONS`, `CANCELLATIONS` | — (takes CSV files only) | — | 5,000 rows |

Training (`POST /hotels/{id}/train`, kind `TRAIN`) is a job too, in the same
queue. Prices aren't saved ahead: the calendar prices on request
([0084](decisions/0084-no-fingerprint-no-price-job.md)).

**Window rules** (`services/domain/window.py`):

| Given | Window |
|---|---|
| start and end | that window |
| start only | start to today |
| end only | the hotel's first booked night to end |

Every backfill walks newest month first, so a run that stops part-way has saved
the most recent events ([0087](decisions/0087-backfills-newest-first-no-alignment.md)).

Events use a 10km radius around the city centre and need `PREDICTHQ_TOKEN`
(a 503 if it isn't set).

**Uploaded files** (`services/ingest/files.py`): `REPORTS` lists each report
kind with the columns it needs. A file is the kind whose columns its header
holds; none or more than one is a 422. Every file is recognised and parsed
before any job is queued, so one bad file is a 422 naming it and nothing is
queued. More than `UPLOAD_MAX_FILES` files, or one over `UPLOAD_MAX_FILE_MB`,
is a 413. Each file's job records its name, sha256, rows, rows skipped and
date range in `params`; a repeated hash is allowed.

### 5.2 Lifecycle

```
POST /hotels/7/ingest/events {"start": "2025-01-01"}
  routes/ingest.ingest_events
    → job_service.start_events_job(session, 7, start=…, end=None)
        get_hotel                                   → 404
        API key set?                                → 503
        resolve_window                              → 422
        same kind already queued or running?        → 409 (not for file jobs)
        job_repo.create_job(params = resolved inputs)
    → tasks.add_task(worker.enqueue, job.id, hotel_id)
  ← 202 {job}                    get_session commits the row first

worker.enqueue(id, hotel_id)     after the response: back of the hotel's queue;
                                 starts the hotel's runner if none is running
worker._drain(hotel_id)          one job at a time, oldest first, until empty
worker.run_job(id)               its own session
  queued → running; commit       (not queued any more, i.e. cancelled → skip)
  for each Step the handler yields:
      save progress; commit; remember step.resume_from
  on a quota error   → rollback; status = stopped, error, resume_from
  on any other error → rollback; status = failed,  error, resume_from
  otherwise          → status = succeeded

GET /jobs/{id}          → status, params, progress, error, resume_from
POST /jobs/{id}/cancel   → queued → cancelled; 409 if running or finished
```

A job's `progress` is committed together with the chunk it describes, so it
always matches what is saved.

**Resuming** is by hand: start the same job again with `end = resume_from`
and the same `start`. Upserts make overlap safe.

**Limits:**

- A hotel's jobs run one at a time, first in, first out; different hotels
  run side by side. A long backfill holds up the hotel's queue behind it.
- A failed job doesn't stop the jobs queued after it.
- One unfinished events, training or tune-up job per hotel; a second
  gets a 409. File jobs stack up in the queue instead.
- A restart, deploy or sleep loses the queues and the parsed files waiting in
  them. On startup every queued or running job is marked failed. That's safe on
  the free plan, where the old process has stopped first; a paid plan needs
  more (0077, "Moving to a paid plan").
- Production runs a single uvicorn worker, because the queues and parsed files
  live in that process.
- Production is a Render free-plan service
  ([0054](decisions/0054-hosted-on-render.md)). It sleeps after 15 minutes
  without requests, which kills running jobs and loses the queues the same
  way a restart does.

### 5.3 Scheduled jobs

With `SCHEDULER_ENABLED`, `worker.schedule_forever` runs from startup
([0077](decisions/0077-scheduled-jobs.md)):

```
every 15 minutes
  scheduler.start_due_jobs(session)
    for each hotel, in order: events, train (SCHEDULED_TRAINING)
      no scheduled run of that kind since SCHEDULE_HOUR (hotel time) last
      passed, or the last one failed 1h ago? Manual runs don't count.
        → the same start_* the routes call; skipped if it can't start
  commit; worker.enqueue each job      same per-hotel queue as uploads
```

Prices aren't saved ahead; the calendar prices on request (0084).

---

## 6. End-to-end flows

### 6.1 A read: `GET /hotels/7/events?start=…`

```
routes/event.list_events
  → services/domain/event.list_events(session, 7, …)
      → get_hotel(7)                                   404 if missing
      → repository/signals/event.list_events(city_id=hotel.city_id, …)
  ← (rows, total)
  → paginate(EventResponse, rows, total, page)
```

### 6.2 A hotel file upload

```
POST /hotels/7/ingest/files  files=DailyNewReservations.csv, Cancellation.csv
  → too many files, or one too big?                      → 413
  → job_service.start_file_jobs
      → ingest/files.parse_files, per file:
          recognise by header (no or several matches)    → 422
          the report's parse; any failure                → 422
      → one job per file (RESERVATIONS, CANCELLATIONS), in upload order
  ← 202 [job, job]; each joins the hotel's queue with its parsed rows
  worker, per job, 5,000 rows at a time:
      reservations / cancellations: upsert_bookings / upsert_cancellations
                                                         → commit
```

Actual & Forecast is no longer read
([0080](decisions/0080-actual-and-forecast-removed.md)): an upload of it is a
422, as an unknown report. Its `daily_performance` table and rows are kept
until the team decides to drop them; Alembic ignores the table
(`RETIRED_TABLES` in `migrations/env.py`).


### 6.3 An events backfill

```
job EVENTS, mode=window, 2025-01-01 … 2025-12-31
  for each month, newest first:
      predicthq.fetch(window_params(city centre, month))
          pages through `next`; each record → NormalizedEvent, or rejected with a reason
      for each event: domain/event.save_event(session, city_id, event)
      yield Step(progress, resume_from = the next, older month's end)   → commit
```

### 6.4 Training and recommendations

Both read only what's already ingested; neither fetches
([0028](decisions/0028-train-and-serve-on-ingested-data.md)).

```
POST /hotels/7/train {"description": "...", "settings": {...}}     → job, 202
  job_service.start_train_job       DOUBLE BAR_RO bookings loaded in window → else 422 (0079)
  → domain/model.prepare_training
      training_data                             shared with the backtest (6.7)
        domain/booking.booking_rows             one row per booked room per night, from
                                                DOUBLE BAR_RO bookings alone: rate = adr_nett,
                                                weight 1 (0076, 0079)
        feedback.current_feedback            drop the rooms of nights tagged one-off (0070)
        domain/inputs.build_inputs          counted events, backfilled nights, first seen
        ml/features.build_features              calendar + holidays + events + lead_days from booked_on
                                                (0055, 0056, 0067); holidays from the
                                                library alone (0083)
      feedback.current_feedback             current version per night with a rate, before or after
      each manager rate is a row of its own, booked the day they saw the recommendation;
                    weight 25% of the night's rooms, at least 1 (0071, 0076)
  progress = {stage: fitting}; commit           frees the connection during the fit (0056)
  → domain/model.fit                    no database
      training_data.combine_identical_rows      same night, same inputs → one weighted row
      EBMModel.fit in a thread                  one fit on every row; no holdout, no range (0085)
        ml/resources.measure                    the fit's time and peak memory into metrics (0046)
  → domain/model.save_version
      model_repo.create_pricing_model           new version, inactive, with its own `features`,
                                                `target` (adr_nett) and room type, DOUBLE,
                                                created the first time (0008, 0009, 0056, 0079)
      model_repo.activate_pricing_model         unless activate=false
  progress = {model_id, version, metrics, ...}

GET /hotels/7/recommendations?date=2026-10-24 | ?start=…&end=…[&room_type_id=]
  → domain/recommendation.get_recommendations             at most 90 nights
      model_repo.get_active_pricing_model       404 if none; artifact not loaded yet
      per night: build_features row (booked_on = today), keep the version's
                 `features`; the night's events, events_source
      snapshot_repo.latest_snapshots            one query for the range
      same model and same inputs as the latest snapshot → return it (0084)
      otherwise → load the model once, score every such night in one batch,
                  store a new snapshot (from today on; past nights aren't stored)
      feedback.current_feedback               the manager's rate per night, read live (0071)
  ← one per night: rate, manager_rate, lead_days, factors in €
```

A version trained on booked rooms also reads days booked ahead
([0056](decisions/0056-lead-days-input.md)): the rate is the price if booked
today, so each night re-prices daily and the response carries `lead_days`.
Serving keeps each version's own `features`, so older versions are unchanged.

A recommendation is stored when it's made and reused while its model and
inputs hold, compared directly
([0038](decisions/0038-recommendations-reused-while-inputs-hold.md),
[0084](decisions/0084-no-fingerprint-no-price-job.md)). Days booked ahead
change daily, so a future night gets a new snapshot on each day it's shown;
asking again the same day returns the same snapshot. There's no separate route
for a night's factors.

Training learns from the manager's rates
([0071](decisions/0071-manager-rate-is-the-target-everywhere.md)): for each
night, the current version of its feedback, if it has a rate, before or after
the night. It's a booked-room row of its own, booked the day the manager saw
the recommendation, weighing 25% of the night's booked rooms and at least 1
([0076](decisions/0076-booked-rooms-only-and-manager-rows.md)); the night's
sales stay as they are. The daily tune-up follows the same rule.
A version's `metrics` count the manager rates it used (`feedback_nights`); which
ones follows from its training window (0086).

Each recommendation also carries `manager_rate`, the rate the manager set for
the night (null if none). It's read live, not stored in the snapshot, so a new
rate never starts a new snapshot.

Every price is before VAT, in and out
([0076](decisions/0076-booked-rooms-only-and-manager-rows.md)): the model learns
`adr_nett`, and the manager sees and types rates on the same basis, so nothing
is converted.

A daily tune-up (`POST /hotels/{id}/tune`, a `tune` job;
[0069](decisions/0069-daily-tune-up.md)) corrects the active model without
retraining it. `domain/tuning.tune` keeps the active model's base as it is and
fits a small EBM on the gap between its predictions and the manager's current
rates, before or after the night. Each row is built as serving built it, with
the base version's stored inputs: a manager row booked the day they set the
rate, an untouched night the day its price was shown (0084)
([0076](decisions/0076-booked-rooms-only-and-manager-rows.md)). Past nights with a snapshot in the 30 days
before today that the manager left alone join with the rate their latest
snapshot showed
([0072](decisions/0072-tune-up-learns-untouched-nights-as-unchanged.md),
[0074](decisions/0074-only-past-nights-are-no-change.md),
[0078](decisions/0078-tune-up-keeps-what-was-shown-and-points-to-its-base.md)),
so the correction keeps what the manager accepted and doesn't shift every
night; future nights don't count, as the manager may still change them.
`ml/ebm.TunedEBMModel` adds the two. It is saved as a new `ebm-tuned` version
that serves by default, whose artifact holds only the correction and whose
`base_model_id` points to the base; `pricing_model.load_model` joins them to
serve, and a base with a tune-up pointing to it can't be deleted (0078). Each
tune-up starts again from the base, so corrections never stack; with fewer than
5 rates it saves nothing. The correction sees every input the base does
([0076](decisions/0076-booked-rooms-only-and-manager-rows.md)); whether to keep
`month` out, as [0075](decisions/0075-correction-ignores-month.md) found
safer, is open. The tune job goes through the hotel's queue like every other
job.

A night whose current feedback is tagged `ONE_OFF` (a buyout, a private event)
teaches the model nothing ([0070](decisions/0070-one-off-nights-teach-the-model-nothing.md)):
`training_data` drops it and its booked rooms, so neither a retrain nor the
backtest sees it, and the tune-up leaves out its rate.

Every training run is a new version
([0029](decisions/0029-every-training-run-is-a-new-version.md)):
`description` says what it tried, and `POST /models/{id}/activate` chooses
which version serves.

### 6.5 Signing in

([0040](decisions/0040-google-sign-in-cookie-sessions.md))

```
GET /auth/google/login
  routes/auth.google_login
    user_service.require_sign_in_configured     503 if a Google setting or SESSION_SECRET is blank
    Authlib saves state, nonce and PKCE verifier in the session cookie
  ← 302 to accounts.google.com

GET /auth/google/callback?code=…&state=…        Google sends the browser back
  routes/auth.google_callback
    Authlib: state matches the cookie's?        no  → 400
             exchange the code, with the verifier
             check the ID token: signature, issuer, audience, expiry, nonce   → 400
    user_service.sign_in(google_id=sub, email, email_verified, name)
      email missing or unverified               → 403
      user_repo.upsert_user                     INSERT … ON CONFLICT DO UPDATE
    session cleared, then {"user_id": id}; get_session commits
  ← 302 to FRONTEND_URL, with the session cookie

GET /auth/me
  routes/access.get_current_user
    user_service.get_signed_in_user(session["user_id"])    401 if none, or the user is gone
  → hotel_service.list_hotels_for_user                     [] until a hotel is linked
```

The cookie is signed, not encrypted, and holds only the user's id. It is
HTTP-only, Secure (a setting) and carries a `SameSite` (a setting). It is
re-issued on every response, so a session ends 14 days after the last request.
A missing, expired or tampered cookie is an empty session, so all three are the
same 401. Logout deletes the browser's cookie; a copied one stays valid until it
expires. CORS allows `FRONTEND_URL` only, with credentials.

### 6.6 Reaching a hotel's data

```
GET /jobs/12                                    a job, by its own id
  main.py: router has dependencies=[get_current_user]       401 if no session
  routes/access.JobId  (the handler's job_id type)
    access_service.require_job(session, user, 12)
      job_repo.get_job → job.hotel_id
      user_repo.has_hotel(user.id, job.hotel_id)
      missing, or not the user's hotel          → NotFoundError → 404, same as unknown
  handler runs only after that

POST /hotels/7/users {"email": "colleague@example.com"}
  HotelId: the caller must be linked to hotel 7             404 if not
  user_service.link_user_by_email
    get_user_by_email                           none → 404 (hasn't signed in), several → 409
    link_user_to_hotel                          idempotent
  ← 204
```

`HotelId`, `JobId` and `ModelId` replace a bare path parameter, so
using one in a handler is what checks access. Tests list every route from
OpenAPI and assert the 401 and the cross-hotel 404 for each. The scheduler, when
it exists, runs in the API process and calls the job services directly with no
user.

### 6.7 Backtest

`just backtest 7 [--baselines] [--inputs …] [--test-days N] [--start DATE]`
checks whether the model, and each input, is
worth having
([0042](decisions/0042-how-the-backtest-judges-the-model.md)). Read-only:
models are trained in memory and thrown away.

```
cli.backtest
  → domain/backtest.load_backtest               then the session closes
      pricing_model.training_data               the same inputs training sees
      cutoff = newest night − test_days (default 90)
  → domain/backtest.run_backtest                no database
      one EBM on --inputs (default: every input the training data has),
        identical rows merged as in training
      score                                     every test row (a booked room)
      on booked rooms: MAE by days booked ahead
      only with --baselines:
        ml/baselines on each night's average    same weekday last year,
          booked rate ≤ cutoff (0076)
                                                last 4 weeks' weekday mean
        score                                   each baseline vs the model
                                                on the nights it covers
  ← scores (+ baseline table)
```

`ml/features.INPUT_GROUPS` sorts every input into groups (calendar, holidays,
events and lead_days); `--inputs` takes group names or single features. Compare
input sets by running it once per set: `--inputs calendar,events` leaves out days
booked ahead. The test rows are booked rooms. `--start` leaves out
earlier nights, and
`--event-days` limits how much event history the model trains on.

---

## 7. API

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | |
| GET | `/auth/google/login` | 302 to Google; open it as a page |
| GET | `/auth/google/callback` | Google's return: starts the session, 302 to the frontend |
| POST | `/auth/logout` | 204; ends the session |
| GET | `/auth/me` | the signed-in user and their hotels; 401 if not signed in |
| POST, GET | `/cities` | any signed-in user |
| GET | `/cities/{id}` | any signed-in user |
| PATCH | `/cities/{id}` | only someone linked to a hotel in the city |
| POST, GET | `/hotels` | a hotel includes its city; POST links its creator; GET lists only your hotels |
| GET, PATCH | `/hotels/{id}` | |
| POST | `/hotels/{id}/users` | `{email}`; links a colleague who has signed in; 204 |
| GET | `/hotels/{id}/events` | paginated; withdrawn events hidden |
| GET | `/hotels/{id}/recommendations?date=` or `?start=&end=` | a list, one per night (≤ 90); stores each night from today on, reusing it while its inputs hold |
| POST | `/hotels/{id}/feedback` | adds feedback on a night, past or future; a change is a new version ([0043](decisions/0043-manager-feedback-is-versioned.md)) |
| GET | `/hotels/{id}/feedback?start=&end=` | current feedback per night (≤ 366); `include_history=true` adds earlier versions |
| GET | `/hotels/{id}/freshness` | when each kind of data last succeeded (recommendations: last rate change), and the latest failure ([0039](decisions/0039-freshness-reports-dates-only.md)) |
| POST | `/hotels/{id}/train` | job, 202; optional description, window, settings |
| GET | `/hotels/{id}/models` | paginated, newest version first |
| GET | `/models/{id}` | one version, no artifact |
| POST | `/models/{id}/activate` | serve this version |
| POST | `/hotels/{id}/ingest/events` | job, 202; optional `{start, end}` |
| POST | `/hotels/{id}/ingest/files` | a job per file, 202; multipart files only, each recognised by its header |
| GET | `/jobs/{id}` | |
| POST | `/jobs/{id}/cancel` | a queued job only; 409 otherwise |
| GET | `/hotels/{id}/jobs` | paginated, newest first |

Status codes: `201` create, `202` job queued, `302` sign-in redirects, `204`
logout, `200` otherwise, and the error codes in 3.2. Every route except
`/health` and `/auth/google/*`, `/auth/logout` needs a session (401). A hotel,
or a job, model or room type of one, that isn't yours is a 404.

---

## 8. Configuration

Settings live in `config.py`, read from `../.env` then `backend/.env`. Every
setting is listed in `.env.example`.

| Setting | Used by |
|---|---|
| `DATABASE_URL`, `DEBUG` | `database/session.py` (`DEBUG` echoes SQL) |
| `PREDICTHQ_TOKEN` | events job |
| `GOOGLE_CLIENT_ID`, `_SECRET`, `GOOGLE_REDIRECT_URI` | the OAuth client in `routes/auth.py`; the 503 check in `services/domain/user.py` |
| `SESSION_SECRET`, `SESSION_MAX_AGE_SECONDS`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE` | the session middleware in `main.py` (the secret also in the 503 check) |
| `FRONTEND_URL` | the CORS origin in `main.py`, and where the callback redirects |
| `UPLOAD_MAX_FILES`, `UPLOAD_MAX_FILE_MB` | the 413 checks in `routes/ingest.py` |

`services/job.py` and `services/domain/user.py` read settings; `main.py` reads
them to build the middleware. A missing key is a 503 when the job or the
sign-in is requested.

---

## 9. Built but not connected

| Piece | State |
|---|---|
| — | nothing at the moment |

Flights, competitor rates and booking-pace inputs were removed
([0050](decisions/0050-drop-flights-and-booking-pace.md)). Weather was
removed ([0081](decisions/0081-weather-removed.md)); events reach the model
([0055](decisions/0055-events-back-in-the-model.md)).

---

## 10. Open questions

1. **Which inputs the model needs.** It reads the calendar, holidays, events
   and days booked ahead (0055, 0056, 0067). Weather was removed (0081).
2. **Scheduling.** The routine refreshes (recent events, the daily tune-up) only run
   when called. Recommendations are stored as they're requested.
3. **Tests.** The suite covers recommendations, freshness
   and users, but not ingest or training. Nothing has been run against a real
   PredictHQ key.
4. **Amended bookings.** A booking keeps the dates it had when first uploaded
   ([0047](decisions/0047-bookings-and-cancellations.md)), and how often dates
   change isn't known, and nothing checks the bookings against the hotel's
   final rooms sold any more (0080).

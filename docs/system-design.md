# Foresight backend: system design

How the backend fits together: the layers, the patterns each one uses, and how
a request or a job moves through them. Written from the code as of 2026-10-15
(`43-implement-ebm`). The reasons behind each choice are in
[`decisions/`](decisions/README.md); this document links to them rather than
repeating them.

---

## 1. The system in one page

Foresight stores a hotel's nightly sales history and the outside signals that
move demand (weather, events, flights), so a pricing model can recommend a
nightly rate.

```
                    ┌──────────────────────────────────────────────┐
  HTTP client ────▶ │ routes     HTTP only: parse, call, map        │
                    └──────────────┬───────────────────────────────┘
                                   │ plain arguments in, domain objects out
                    ┌──────────────▼───────────────────────────────┐
  worker.py ──────▶ │ services                                      │
  (background jobs) │   domain/    rules and reads per domain       │
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
- **Jobs** (ingesting weather, events and performance data). The request
  validates the input, stores a job and returns `202` at once. The job runs in
  the background in the same process and commits after every chunk.

Everything is async: FastAPI handlers, SQLAlchemy sessions and every outside
HTTP call. People sign in with Google ([0040](decisions/0040-google-sign-in-cookie-sessions.md)),
every route but `/health` and `/auth/*` needs a signed-in user, and a hotel is
reachable only by a user linked to it ([0041](decisions/0041-login-required-hotels-by-link.md)).

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
    city.py hotel.py weather.py event.py flight.py ingest.py job.py
    pricing_model.py feedback.py health.py
    auth.py                Google sign-in, logout, /auth/me
    access.py              CurrentUserDep
  services/
    errors.py              NotFound / Conflict / InvalidRequest / NotConfigured /
                           NotSignedIn / Forbidden
    job.py                 job kinds, validation, handlers, lifecycle
    domain/                booking, city, hotel, user, weather, weather_coverage, event, flight,
                           model_inputs, pricing_model, recommendation, feedback, freshness
    ingest/                weather, event, performance, bookings, window
    adapters/              open_meteo, predicthq, aerodatabox, opensky, cso,
                           hotel_csv, guestline, normalize, textdates
    ml/                    base, ebm, features, weighting, baselines
  repository/
    upsert.py pagination.py
    booking.py city.py hotel.py job.py pricing_model.py recommendation.py feedback.py
    user.py
    signals/               weather, event, flight, competitor_rate
  database/
    base.py enums.py session.py
    models/                booking, city, hotel, job, pricing_model, recommendation, feedback,
                           user
      signals/             weather, event, flight, competitor_rate
    migrations/
```

`example_widget.py` in each layer is a small reference slice that shows every
pattern in this document.

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
 │   └─ InvalidWindowError  (services/ingest/window.py)
 ├─ NotConfiguredError    ─────────▶   503   (an API key or secret isn't set)
 ├─ NotSignedInError      ─────────▶   401   (no valid session)
 └─ ForbiddenError        ─────────▶   403   (known, but not allowed)
```

- Every `get_x(id)` in a service raises `NotFoundError`; nothing returns None
  to a route.
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
| a night (stay, weather day, event date, arrival day) | `Date`, local to the city ([0023](decisions/0023-stay-nights-are-local-dates.md)) |
| an instant | `DateTime(timezone=True)` |
| enums | VARCHAR holding the member name; adding a member needs no migration |
| raw source payloads | `JSONB`, kept verbatim |

### 3.5 Idempotent writes

Every write from an outside source or a file is an upsert on a natural key
([0018](decisions/0018-idempotent-upserts.md)):

| Table | Natural key |
|---|---|
| `weather` | city_id, weather_date, is_forecast, source |
| `flight_arrivals` | city_id, arrival_date, source |
| `competitor_rates` | city_id, hotel_name, stay_date, source |
| `daily_performance` | room_type_id, stay_date |
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
- Derived values (occupancy, ADR, RevPAR) are `@computed_field`s, never stored.

Lists that grow without bound take `?limit=&offset=` (default 50, max 200) and
return `{"items", "total", "limit", "offset"}`: performance, weather, events,
flight arrivals and jobs. Cities, hotels and room types return a plain list.

### 3.7 Outside HTTP

Adapters make each request once and raise on failure; there are no automatic
retries ([0022](decisions/0022-no-retries-resume-instead.md)). Each adapter
turns its source's quota responses into a named error:

| Source | Quota error |
|---|---|
| PredictHQ | 402/403 → `OutOfCreditsError`; 429 → `RateLimitedError` |
| AeroDataBox | 429 → `RateLimitedError`; paces requests 1.1s apart |
| OpenSky | 429 → `CreditsExhaustedError`; refreshes its token on 401 |
| Open-Meteo, CSO | none; any failure raises |

---

## 4. Data model

```
cities ─┬─< hotels ─┬─< room_types ─< daily_performance   (the hotel's own history)
        │           ├─< bookings                          (rooms booked, still live; 0047)
        │           ├─< booking_cancellations             (rooms cancelled; linked by book_ref)
        │           ├─< pricing_models ─< pricing_model_feedback >─ feedback
        │           │                                     (trained models; one active; the
        │           │                                      feedback each one used; 0044)
        │           ├─< recommendation_snapshots          (every rate recommended; 0038)
        │           ├─< feedback (also > room_types)      (the manager's view of a night; 0043)
        │           └─< jobs                              (ingest runs)
        │
        ├─< weather                                       ┐
        ├─< events ─< event_observations                  │ outside signals,
        ├─< flight_arrivals                               │ shared by every hotel
        └─< competitor_rates                              ┘ in the city

users ─< user_hotels >─ hotels                              (who works for which hotel)
users ─< feedback >─ recommendation_snapshots               (who said it; the rate they saw)
```

**Cities are the market** ([0017](decisions/0017-cities-are-the-market.md)).
A city holds its name, a unique normalized slug, country, IANA timezone,
centre coordinates and both airport codes. Weather is read and events are
searched at the centre; "today" for a job is today in the city's timezone. A
hotel keeps its own coordinates for distance to venues.

**Users** ([0035](decisions/0035-users-keyed-on-google-id.md)) are Google
accounts, identified by Google's account id and never by email (`users.email`
is not unique). `user_hotels` links a user to a hotel, keyed on the pair so
linking twice changes nothing; a hotel can have several users, a user can
belong to several hotels, and a user with none is valid. Signing in with Google
creates the user, or refreshes the existing one's email, name and
`last_signed_in_at` ([0040](decisions/0040-google-sign-in-cookie-sessions.md)).
Creating a hotel links its creator, and any member can link a colleague with
`POST /hotels/{id}/users` ([0042](decisions/0042-link-users-through-the-api.md)).
A hotel is reachable only through its link ([0041](decisions/0041-login-required-hotels-by-link.md)).

**Feedback** ([0043](decisions/0043-manager-feedback-is-versioned.md)) is what
the manager says about a night's rate: a required verdict, an optional rate,
and a reason as tags from a fixed list, free text, or both. Rows are only added;
a change is the next `version` for that room type and night, the highest is
current, and earlier ones keep their times. It records the snapshot the manager
saw (null for a past night never saved), whether it came before or after the
night (set by the server), and who gave it (null for feedback saved before sign-in was required).

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

Long work runs as jobs inside the API process
([0020](decisions/0020-jobs-in-the-api-process.md)), one kind per signal
([0021](decisions/0021-one-ingest-job-per-signal.md)).

### 5.1 Kinds

| `POST /hotels/{id}/ingest/…` | Kind | No dates | With dates | Chunk |
|---|---|---|---|---|
| `weather` | `WEATHER` | next 16 days of forecast | recorded weather for past days, forecast for the next 16 | one year of recorded; the forecast |
| `events` | `EVENTS` | events PredictHQ revised since the last refresh (7 days the first time) | every event active in the window | one month |
| `performance` (multipart) | `PERFORMANCE` | — (takes CSV files and `base_rate`) | — | one file |

**Window rules** (`services/ingest/window.py`):

| Given | Window |
|---|---|
| start and end | that window |
| start only | start to today |
| end only | the hotel's first loaded night to end, walked newest first |

Weather days beyond the forecast have no source; they're listed in the job's
`progress.beyond_forecast` instead of being fetched.

Events use a 10km radius around the city centre and need `PREDICTHQ_TOKEN`
(a 503 if it isn't set). Performance files are all parsed before the job is
queued, so one bad file is a 422 and nothing is saved.

### 5.2 Lifecycle

```
POST /hotels/7/ingest/events {"start": "2025-01-01"}
  routes/ingest.ingest_events
    → job_service.start_events_job(session, 7, start=…, end=None)
        get_hotel                                   → 404
        API key set?                                → 503
        resolve_window                              → 422
        same kind already queued or running?        → 409
        job_repo.create_job(params = resolved inputs)
    → tasks.add_task(worker.run_job, job.id)
  ← 202 {job}                    get_session commits the row first

worker.run_job(id)               after the response, its own session
  status = running; commit
  for each Step the handler yields:
      save progress; commit; remember step.resume_from
  on a quota error   → rollback; status = stopped, error, resume_from
  on any other error → rollback; status = failed,  error, resume_from
  otherwise          → status = succeeded

GET /jobs/{id}    → status, params, progress, error, resume_from
```

A job's `progress` is committed together with the chunk it describes, so it
always matches what is saved.

**Resuming** is by hand: start the same job again with `start = resume_from`
(or `end = resume_from` for a run walking backwards). Upserts make overlap
safe.

**Limits:**

- Jobs start immediately and run side by side; there's no ordering.
- One unfinished job per kind per hotel; a second request gets a 409.
- A restart kills running jobs. On startup they're marked failed.
- Production runs a single uvicorn worker, because jobs and a performance
  job's parsed files live in that process.
- Nothing runs on a schedule; the routine refreshes run when called.

---

## 6. End-to-end flows

### 6.1 A read: `GET /hotels/7/weather?start=…`

```
routes/weather.list_weather
  → services/domain/weather.list_weather(session, 7, …)
      → get_hotel(7)                                   404 if missing
      → repository/signals/weather.list_weather(city_id=hotel.city_id, …)
          → fetch_page(SELECT … WHERE city_id = … ORDER BY weather_date, id)
  ← (rows, total)
  → paginate(WeatherResponse, rows, total, page)
```

### 6.2 A performance import

```
POST /hotels/7/ingest/performance  files=a.csv,b.csv  base_rate=150
  → start_performance_job
      → ingest/performance.parse_files: HotelDataParser per file
          load → clean → transform → validate (pandas); any failure → 422
      → queue the job; parsed rows go to the worker in memory
  worker, per file:
      upsert_room_type("Standard", room_count from the file, base_rate)
      upsert_daily_performance(rows)                     → commit
```

The client's export has one room type, so every night is stored under
"Standard". The rate is revenue divided by rooms sold, because the export has
no listed price.
Blocks, ROOS and Waitlist are saved too when the export has them; older
exports leave new nights empty and never clear a stored value. Occupancy is
rooms sold ÷ (rooms in stock − rooms out of service), capped at 100%, so a
sold-out night is 100% even when Guestline's Occ% shows 99%
([0037](decisions/0037-three-guestline-reports.md)). Blked and DFS aren't read
until their meaning is known.


### 6.3 An events backfill

```
job EVENTS, mode=window, 2025-01-01 … 2025-12-31
  for each month:
      predicthq.fetch(window_params(city centre, month))
          pages through `next`; each record → NormalizedEvent, or rejected with a reason
      for each event: domain/event.save_event(session, city_id, event)
      yield Step(progress, resume_from = next month's start)   → commit
```

### 6.4 Training and recommendations

Both read only what's already ingested; neither fetches
([0028](decisions/0028-train-and-serve-on-ingested-data.md)).

```
POST /hotels/7/train {"description": "...", "settings": {...}}     → job, 202
  job_service.start_train_job       hotel exists, nights loaded in window → 422
  → domain/pricing_model.train
      training_data                             shared with the backtest (6.7)
        hotel_repo.list_nights                  every night, oldest first
        ml/weighting.training_mask              drop unpriced nights (0004)
        domain/model_inputs.weather_for         recorded weather only
        domain/model_inputs.events_for          counted events + fetched nights (0041)
        ml/features.build_features              unfetched nights' events empty; flights empty
        ml/weighting.sample_weights             occupancy of sellable rooms (0003)
      feedback_repo.training_feedback           current version per night, after the night only
      ml/feedback.apply_feedback                manager's rate replaces the rate; verdict weights (0044)
      EBMModel.fit in a thread                  calibrates on the newest 15%, then refits on all (0005, 0045)
        ml/resources.measure                    the fit's time and peak memory into metrics (0046)
      model_repo.create_pricing_model           new version, inactive (0008, 0009)
      model_repo.link_feedback                  records which feedback this version used
      model_repo.activate_pricing_model         unless activate=false
  progress = {model_id, version, metrics, ...}

GET /hotels/7/recommendations?date=2026-10-24 | ?start=…&end=…[&room_type_id=]
  → domain/recommendation.get_recommendations             at most 90 nights
      model_repo.get_active_pricing_model       404 if none; artifact not loaded yet
      per night: build_features row, events_by_night (0032), weather source (0024),
                 events source (0041)
      fingerprint = sha256(model id + those inputs)
      snapshot_repo.latest_snapshots            one query for the range
      fingerprint matches → reuse the snapshot; the model doesn't run
      otherwise → load the model once, score every such night in one batch,
                  store a new snapshot (from today on; past nights aren't stored)
  ← one per night: rate, 80% interval, factors in €, events, weather source
```

A recommendation is stored when it's made and reused while its inputs hold
([0038](decisions/0038-recommendations-reused-while-inputs-hold.md)). Asking
for a night again returns its stored snapshot while nothing it reads has
changed, so there's no separate route for a night's factors.

Training learns from the manager's feedback
([0044](decisions/0044-train-on-feedback-given-after-the-night.md)): for each
night, the current version of its feedback, if it was given after the night.
A rate on the right side of the verdict replaces the night's training rate
(within 30% of what was recorded); a verdict with no rate halves the night's
weight and "about right" doubles it. Feedback from before the night isn't
used. Each model version records the feedback it used in
`pricing_model_feedback`, and its `metrics` count it.

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

([0041](decisions/0041-login-required-hotels-by-link.md),
[0042](decisions/0042-link-users-through-the-api.md))

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

`HotelId`, `JobId`, `ModelId` and `RoomTypeId` replace a bare path parameter, so
using one in a handler is what checks access. Tests list every route from
OpenAPI and assert the 401 and the cross-hotel 404 for each. The scheduler, when
it exists, runs in the API process and calls the job services directly with no
user ([0041](decisions/0041-login-required-hotels-by-link.md)).

### 6.7 Backtest

`just backtest 7 [--baselines] [--inputs …] [--test-days N] [--event-days N]` checks
whether the model, and each input, is worth having
([0042](decisions/0042-how-the-backtest-judges-the-model.md)). Read-only:
models are trained in memory and thrown away.

```
cli.backtest
  → domain/backtest.run_backtest
      pricing_model.training_data               the same inputs training sees
      cutoff = newest night − test_days (default 90)
      one EBM on --inputs (default: all FEATURES)
      only with --event-days:
        event inputs blanked before cutoff − N  other inputs keep all history
      ml/base.score                             every test night
      only with --baselines:
        ml/baselines on nights ≤ cutoff         same weekday last year,
                                                last 4 weeks' weekday mean
        ml/base.score                           each baseline vs the model
                                                on the nights it covers
  ← scores (+ baseline table), and a PNG in backend/backtest-out/
```

`ml/features.INPUT_GROUPS` sorts every feature into calendar, weather,
events (holiday flags included) and flights; `--inputs` takes group names or
single features. Compare input sets by running it once per set.
`--event-days N` limits only the event inputs to the N days before the
cutoff, to see how much event history the model needs.

### 6.8 How full a night was on an earlier date

Computed when asked, never stored
([0048](decisions/0048-rooms-booked-rebuilt-when-asked.md)). There's no route yet.

```
domain/booking.booking_curves(session, 7, start=…, end=…)
  get_hotel                                       404 if missing
  booking_repo.list_live_bookings                 no cancellation for the ref
  booking_repo.list_cancellations
  per night of each stay: +1 the day booked, −1 the day cancelled
← {night: {day the count changed: rooms booked at the end of that day}}

domain/booking.rooms_on(curve, as_of)             reads one night at any date
domain/booking.rooms_booked(session, 7, night=…, as_of=…)     one night
domain/booking.check_final_counts(session, 7, start=…, end=…)
  each night's curve the day after it, minus rooms sold from list_nights
```

Pass `check_final_counts` nights the booking export fully covers; for the first
hotel that's from 21 Dec 2024 ([guestline-data.md](guestline-data.md)).

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
| POST, GET | `/hotels/{id}/room-types` | |
| GET | `/room-types/{id}` | |
| GET | `/hotels/{id}/performance` | paginated |
| GET | `/hotels/{id}/weather` | paginated; forecast and recorded rows |
| GET | `/hotels/{id}/coverage/weather` | recorded-weather gaps in a window |
| GET | `/hotels/{id}/events` | paginated; withdrawn events hidden |
| GET | `/hotels/{id}/flight-arrivals` | paginated; one row per source per day |
| GET | `/hotels/{id}/recommendations?date=` or `?start=&end=` | a list, one per night (≤ 90); stores each night from today on, reusing it while its inputs hold |
| POST | `/hotels/{id}/feedback` | adds feedback on a night, past or future; a change is a new version ([0043](decisions/0043-manager-feedback-is-versioned.md)) |
| GET | `/hotels/{id}/feedback?start=&end=` | current feedback per night (≤ 366); `include_history=true` adds earlier versions |
| GET | `/hotels/{id}/freshness` | when each kind of data last succeeded (recommendations: last rate change), and the latest failure ([0039](decisions/0039-freshness-reports-dates-only.md)) |
| POST | `/hotels/{id}/train` | job, 202; optional description, window, settings |
| GET | `/hotels/{id}/models` | paginated, newest version first |
| GET | `/models/{id}` | one version, no artifact |
| POST | `/models/{id}/activate` | serve this version |
| POST | `/hotels/{id}/ingest/{weather,events}` | job, 202; optional `{start, end}` |
| POST | `/hotels/{id}/ingest/performance` | job, 202; multipart files + `base_rate` |
| GET | `/jobs/{id}` | |
| GET | `/hotels/{id}/jobs` | paginated, newest first |
| POST, GET | `/example/widgets`, `/example/widgets/{id}` | reference slice |

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
| `XRAPIDAPI_KEY` | AeroDataBox adapter (no job yet) |
| `OPENSKY_CLIENT_ID`, `_SECRET` | OpenSky adapter (no job yet) |
| `GOOGLE_CLIENT_ID`, `_SECRET`, `GOOGLE_REDIRECT_URI` | the OAuth client in `routes/auth.py`; the 503 check in `services/domain/user.py` |
| `SESSION_SECRET`, `SESSION_MAX_AGE_SECONDS`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE` | the session middleware in `main.py` (the secret also in the 503 check) |
| `FRONTEND_URL` | the CORS origin in `main.py`, and where the callback redirects |

`services/job.py` and `services/domain/user.py` read settings; `main.py` reads
them to build the middleware. A missing key is a 503 when the job or the
sign-in is requested.

---

## 9. Built but not connected

| Piece | State |
|---|---|
| `adapters/aerodatabox.py`, `opensky.py` | work; no flights job yet, so `flight_arrivals` stays empty |
| `adapters/cso.py` | monthly airport passengers; needs a monthly table before it can be stored |
| `competitor_rates` | table and upsert; no source |
| `ingest/bookings.py` | parses and saves bookings and cancellations; no upload route yet (#89) |
| `domain/booking.py` | the rebuild of how full a night was; nothing calls it yet (#103) |

---

## 10. Open questions

1. **Events and flights in the model.** Both have feature columns but no
   history to train on (PredictHQ shows only recent months; no flights job).
2. **Choosing between sources.** Weather is decided (recorded beats forecast).
   Which flight source wins, and whether CSO's monthly totals are spread over
   days, isn't.
3. **Flights ingest.** Waiting on the CSO table and the choice in question 2.
4. **Scheduling.** The routine refreshes (forecast, recent events) only run
   when called. Recommendations are stored as they're requested.
5. **Tests.** The suite covers recommendations, events on a night, freshness
   and users, but not ingest or training. Nothing has been run against real
   PredictHQ, AeroDataBox or OpenSky keys.
6. **Amended bookings.** A booking keeps the dates it had when first uploaded
   ([0047](decisions/0047-bookings-and-cancellations.md)), and how often dates
   change isn't known. The rebuild (6.5) matches final rooms sold, but nothing
   independent checks its counts at earlier dates.

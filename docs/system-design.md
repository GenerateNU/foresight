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
                    │   ml/        pricing model (not wired in yet) │
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
HTTP call. The API has no authentication ([0026](decisions/0026-no-authentication.md)).

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
routes      → services, database.enums, worker (to schedule a job)
services    → repository, database.models/enums, config (job.py only)
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
  main.py                  app, routers, error handlers, lifespan
  config.py                settings (pydantic-settings)
  worker.py                runs jobs; commits per chunk
  routes/
    helpers.py             SessionDep, schema bases, PageResponse, paginate
    errors.py              domain error → status code
    city.py hotel.py weather.py event.py flight.py job.py health.py
  services/
    errors.py              NotFound / Conflict / InvalidRequest / NotConfigured
    job.py                 job kinds, validation, handlers, lifecycle
    domain/                city, hotel, weather, weather_coverage, event, flight, recommendation
    ingest/                weather, event, performance, window
    adapters/              open_meteo, predicthq, asknews, aerodatabox, opensky, cso,
                           hotel_csv, normalize, textdates
    ml/                    base, ebm, features, weighting
  repository/
    upsert.py pagination.py
    city.py hotel.py job.py pricing_model.py
    signals/               weather, event, flight, competitor_rate
  database/
    base.py enums.py session.py
    models/                city, hotel, job, pricing_model
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
 └─ NotConfiguredError    ─────────▶   503   (an API key isn't set)
```

- Every `get_x(id)` in a service raises `NotFoundError`; nothing returns None
  to a route.
- The repository returns None for a missing row or a duplicate insert. The
  service decides that it is an error.
- Every error body is `{"detail": "..."}`.
- Adapter errors (`OutOfCreditsError`, `RateLimitedError`, ...) never reach
  HTTP. They end a job as `stopped` or `failed` (section 5).

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
  shown in `/docs`.
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
| Open-Meteo, AskNews, CSO | none; any failure raises |

---

## 4. Data model

```
cities ─┬─< hotels ─┬─< room_types ─< daily_performance   (the hotel's own history)
        │           ├─< pricing_models                    (trained models; one active)
        │           └─< jobs                              (ingest runs)
        │
        ├─< weather                                       ┐
        ├─< events ─< event_observations                  │ outside signals,
        ├─< flight_arrivals                               │ shared by every hotel
        └─< competitor_rates                              ┘ in the city
```

**Cities are the market** ([0017](decisions/0017-cities-are-the-market.md)).
A city holds its name, a unique normalized slug, country, IANA timezone,
centre coordinates and both airport codes. Weather is read and events are
searched at the centre; "today" for a job is today in the city's timezone. A
hotel keeps its own coordinates for distance to venues.

**Foreign keys** always state `ON DELETE`:

- `CASCADE` from a city to its signals, and from a hotel to its room types,
  nights, pricing models and jobs.
- `RESTRICT` from a hotel to its city: a city with hotels can't be deleted.
- `SET NULL` from an observation to its event, so raw sightings survive.

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
  routes/job.ingest_events
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

### 6.3 An events backfill

```
job EVENTS, mode=window, 2025-01-01 … 2025-12-31
  for each month:
      predicthq.fetch(window_params(city centre, month))
          pages through `next`; each record → NormalizedEvent, or rejected with a reason
      for each event: domain/event.save_event(session, city_id, event)
      yield Step(progress, resume_from = next month's start)   → commit
```

### 6.4 A recommendation (placeholder)

`GET /hotels/7/recommendations?date=…` returns a fixed placeholder
(`is_placeholder: true`) in the final response shape. The pieces that will
feed it exist but aren't connected:

```
daily_performance + weather + events + flights
  → ml/features.build_features     same function for training and serving (0007)
  → ml/weighting.sample_weights    training nights weighted by occupancy (0003)
  → ml/ebm.EBMModel                fit, predict with interval, explain (0001, 0005, 0006)
  → repository/pricing_model       stored in Postgres, one active per hotel (0008, 0009)
```

Weather for future nights follows [0024](decisions/0024-weather-for-future-nights.md).

---

## 7. API

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | |
| POST, GET | `/cities` | |
| GET, PATCH | `/cities/{id}` | |
| POST, GET | `/hotels` | a hotel includes its city |
| GET, PATCH | `/hotels/{id}` | |
| POST, GET | `/hotels/{id}/room-types` | |
| GET | `/room-types/{id}` | |
| GET | `/hotels/{id}/performance` | paginated |
| GET | `/hotels/{id}/weather` | paginated; forecast and recorded rows |
| GET | `/hotels/{id}/coverage/weather` | recorded-weather gaps in a window |
| GET | `/hotels/{id}/events` | paginated; withdrawn events hidden |
| GET | `/hotels/{id}/flight-arrivals` | paginated; one row per source per day |
| GET | `/hotels/{id}/recommendations?date=` | placeholder |
| POST | `/hotels/{id}/ingest/{weather,events}` | job, 202; optional `{start, end}` |
| POST | `/hotels/{id}/ingest/performance` | job, 202; multipart files + `base_rate` |
| GET | `/jobs/{id}` | |
| GET | `/hotels/{id}/jobs` | paginated, newest first |
| POST, GET | `/example/widgets`, `/example/widgets/{id}` | reference slice |

Status codes: `201` create, `202` job queued, `200` otherwise, and the error
codes in 3.2.

---

## 8. Configuration

Settings live in `config.py`, read from `../.env` then `backend/.env`. Every
setting is listed in `.env.example`.

| Setting | Used by |
|---|---|
| `DATABASE_URL`, `DEBUG` | `database/session.py` (`DEBUG` echoes SQL) |
| `PREDICTHQ_TOKEN` | events job |
| `ASKNEWS_CLIENT_ID`, `_SECRET` | AskNews adapter (no job yet) |
| `XRAPIDAPI_KEY` | AeroDataBox adapter (no job yet) |
| `OPENSKY_CLIENT_ID`, `_SECRET` | OpenSky adapter (no job yet) |

Only `services/job.py` reads settings. A missing key is a 503 when the job is
requested.

---

## 9. Built but not connected

| Piece | State |
|---|---|
| `services/ml/*` | built and decided (0001–0009); nothing trains or serves |
| `repository/pricing_model.py` | built; no service or endpoint |
| `adapters/aerodatabox.py`, `opensky.py` | work; no flights job yet, so `flight_arrivals` stays empty |
| `adapters/cso.py` | monthly airport passengers; needs a monthly table before it can be stored |
| `adapters/asknews.py` | news-extracted events; no job yet |
| `competitor_rates` | table and upsert; no source |

---

## 10. Open questions

1. **Training and serving.** When training runs (likely a job), which nights it
   trains on, how features are read from four tables, and how the
   recommendation endpoint loads the active model.
2. **Choosing between sources.** Weather is decided (recorded beats forecast).
   Which flight source wins, and whether CSO's monthly totals are spread over
   days, isn't.
3. **Flights ingest.** Waiting on the CSO table and the choice in question 2.
4. **Scheduling.** The routine refreshes (forecast, recent events) only run
   when called.
5. **Tests.** The suite predates this design and hasn't been updated. Nothing
   has been run against real PredictHQ, AskNews, AeroDataBox or OpenSky keys.

# File guide

One line per file: what it's for. For how the pieces fit together, see
[system-design.md](system-design.md).

## Root

| File | What it does |
|---|---|
| `README.md` | Project intro and setup steps |
| `AGENTS.md` | Rules for AI coding agents: layers, commands, conventions |
| `justfile` | Dev commands: `just dev`, `migrate`, `test`, `lint`, `backtest`… |
| `docker-compose.yml` | Local stack: Postgres, migrations, backend |
| `docker-compose.neon.yml` | Overlay that points the stack at Neon instead of local Postgres |
| `neon.ts`, `package.json`, `package-lock.json`, `.neon` | Neon CLI config and project link (used by `neon env pull`) |
| `.env.example` | Every setting, with comments; copy to `.env` |
| `.pre-commit-config.yaml` | ruff + Conventional Commit checks on commit |
| `.gitignore` | What git skips |
| `.github/workflows/ci.yml` | CI: PR title, commit messages, lint, tests, migration checks |
| `.github/pull_request_template.md` | PR description template |

## backend/ (setup)

| File | What it does |
|---|---|
| `pyproject.toml`, `uv.lock` | Python dependencies and ruff/pytest config |
| `Dockerfile` | Dev (hot reload) and prod images |
| `alembic.ini` | Alembic config |
| `.env.example` | Optional backend-only overrides |
| `.python-version`, `.dockerignore` | Python version; Docker build excludes |
| `data/*.csv` | Synthetic Guestline exports (performance, bookings, cancellations) used by tests |
| `data/generate.py` | Writes those synthetic CSVs |

## backend/foresight/ (app entry points)

| File | What it does |
|---|---|
| `main.py` | Builds the FastAPI app: routers, session/CORS middleware, error handlers, `/docs` |
| `config.py` | All settings (pydantic-settings), read from `.env` |
| `worker.py` | Runs background jobs; commits after each chunk |
| `cli.py` | Operator commands: `link-user`, `backtest` (+ plot) |

## routes/ — HTTP layer

| File | What it does |
|---|---|
| `helpers.py` | Request/response schema bases, session dependency, pagination |
| `errors.py` | Maps domain errors to HTTP status codes |
| `access.py` | Current user; `HotelId`/`JobId`/… types that check access |
| `auth.py` | Google sign-in, callback, logout, `/auth/me` |
| `health.py` | `/health` |
| `city.py` | Create, list, read, update cities |
| `hotel.py` | Hotels, room types, performance, linking users, recommendations |
| `weather.py` | List weather; recorded-weather coverage gaps |
| `event.py` | List events in a hotel's city |
| `ingest.py` | Start weather, events or performance ingest jobs |
| `job.py` | Read jobs; data freshness |
| `pricing_model.py` | Train, list, read and activate model versions |
| `feedback.py` | Add and list manager feedback on rates |

## services/ — business logic

| File | What it does |
|---|---|
| `errors.py` | Domain errors (`NotFound`, `Conflict`, `InvalidRequest`, …) |
| `job.py` | Job kinds, validation, handlers and lifecycle |

### services/domain/

| File | What it does |
|---|---|
| `access.py` | Checks a user may reach a hotel, job, model, room type or city |
| `user.py` | Sign-in, users, linking users to hotels |
| `city.py` | City rules; "today" in a city's timezone |
| `hotel.py` | Hotels, room types, nightly performance |
| `weather.py` | Read weather for a hotel's city |
| `weather_coverage.py` | Which days lack recorded weather |
| `event.py` | Merge event sightings into one row per event; list events |
| `booking.py` | Rebuild how many rooms were booked for a night on any past date |
| `pricing_model.py` | Training data, train a version, list/activate versions |
| `recommendation.py` | Price nights with the active model; snapshots; explanations |
| `feedback.py` | Save and list versioned manager feedback |
| `freshness.py` | When each kind of data last refreshed |
| `backtest.py` | Train on older nights, score on the newest; baselines |

### services/ingest/ — fetch/parse and save, in chunks

| File | What it does |
|---|---|
| `window.py` | Works out the date window from optional start/end |
| `weather.py` | Fetch and save forecast and recorded weather |
| `event.py` | Fetch and save PredictHQ events (recent or by window) |
| `performance.py` | Parse and save nightly performance CSVs |
| `bookings.py` | Parse and save Guestline bookings/cancellations (no route yet) |

### services/adapters/ — outside APIs and files, no DB

| File | What it does |
|---|---|
| `open_meteo.py` | Open-Meteo forecast and recorded weather |
| `predicthq.py` | PredictHQ events → normalized events |
| `normalize.py` | Shared event shape, title/city normalizing, dedupe key |
| `hotel/actual_forecast.py` | Parses the Guestline Actual & Forecast export |
| `hotel/reservations.py` | Parses the Guestline Daily New Reservations export |
| `hotel/cancellations.py` | Parses the Guestline Cancellations export |
| `hotel/common.py` | Shared row-by-row CSV reading and value checks for the Guestline exports |

### services/ml/ — the model

| File | What it does |
|---|---|
| `features.py` | `FEATURES` (room type, weekday, month) and `build_features` |
| `base.py` | Model base class and `score` (MAE, RMSE, coverage…) |
| `ebm.py` | The EBM pricing model: fit, interval, uncertainty, explain, save/load |
| `weighting.py` | Drops unpriced nights; weights nights by occupancy |
| `feedback.py` | Applies manager feedback to training rates and weights |
| `baselines.py` | Simple rules the model must beat (last year, recent weekdays) |
| `resources.py` | Measures a fit's time and peak memory |

## repository/ — the only code that queries

| File | What it does |
|---|---|
| `upsert.py` | Shared bulk upsert with new/updated/unchanged counts |
| `pagination.py` | Shared limit/offset paging |
| `city.py`, `hotel.py`, `user.py`, `job.py` | Queries for those tables |
| `booking.py` | Bookings and cancellations |
| `pricing_model.py` | Model versions, artifacts, activation, feedback links |
| `recommendation.py` | Recommendation snapshots |
| `feedback.py` | Feedback rows, incl. what training uses |
| `signals/weather.py`, `signals/event.py` | Weather; events and their sightings |

## database/

| File | What it does |
|---|---|
| `base.py` | SQLAlchemy base with constraint naming convention |
| `enums.py` | Enums stored in columns (job kinds, event categories, verdicts…) |
| `session.py` | Engine and per-request session |
| `models/city.py` | `cities` |
| `models/hotel.py` | `hotels`, `room_types`, `daily_performance` |
| `models/user.py` | `users`, `user_hotels` |
| `models/job.py` | `jobs` |
| `models/booking.py` | `bookings`, `booking_cancellations` |
| `models/pricing_model.py` | `pricing_models`, `pricing_model_feedback` |
| `models/recommendation.py` | `recommendation_snapshots` |
| `models/feedback.py` | `feedback` |
| `models/signals/weather.py`, `models/signals/event.py` | `weather`; `events`, `event_observations` |
| `migrations/env.py`, `script.py.mako` | Alembic runner and new-migration template |
| `migrations/versions/*.py` | Schema history, one change per file |

## backend/tests/

| File | What it covers |
|---|---|
| `conftest.py` | Fixtures: rolled-back DB session, a priced hotel, API client, sign-in |
| `test_health.py` | `/health` |
| `test_auth.py` | Google sign-in and session cookie |
| `test_user.py` | Users and hotel links |
| `test_access.py` | Every route needs login; other hotels' data is 404 |
| `test_performance.py` | Performance CSV import |
| `test_bookings.py` | Bookings/cancellations import |
| `test_rooms_booked.py` | Rooms-booked rebuild |
| `test_freshness.py` | Freshness report |
| `test_feedback.py` | Adding and listing feedback |
| `test_feedback_training.py` | How feedback changes training |
| `test_recommendation_snapshots.py` | Snapshot reuse and repricing |
| `test_recommendation_range.py` | Bad recommendation date ranges |
| `test_ebm.py` | EBM fit and holdout scores |
| `test_baselines.py` | Backtest baselines |
| `test_backtest_inputs.py` | `--inputs` parsing |
| `test_resources.py` | Time/memory measuring |

## frontend/ (mock UI, not connected to the API)

| File | What it does |
|---|---|
| `index.html`, `src/main.jsx` | Page shell and React entry |
| `src/App.jsx`, `src/App.css`, `src/index.css` | The pricing demo page and styles |
| `src/pricing.js` | Hard-coded mock prices from the design |
| `src/components/*.jsx` | Option picker, events list, price breakdown chart |
| `src/assets/foresight-logo.svg`, `public/favicon.svg` | Logo, favicon |
| `package.json`, `vite.config.js`, `eslint.config.js` | Frontend deps, build, lint |

## docs/

| File | What it does |
|---|---|
| `system-design.md` | How the backend fits together |
| `decisions/` | One file per design decision; `README.md` is the index |
| `guestline-data.md` | What the hotel's Guestline exports contain |
| `mvp.md` | MVP user stories and open questions |
| `designs/*.png` | UI design screenshots |
| `file-guide.md` | This file |

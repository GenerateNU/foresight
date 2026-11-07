# Foresight

AI revenue intelligence platform for boutique hotels. Combines the hotel's history with events and weather to recommend optimal room rates.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Docker](https://www.docker.com/) — for PostgreSQL (and optional containerized backend)
- [just](https://github.com/casey/just) — command runner

## Quick Start

```bash
# Build the backend image
just build

# Start everything (db + backend with hot reload)
just dev

# Run migrations
just migrate

# View logs
just logs

# Stop everything
just destroy
```

### Local vs Neon database

Recipes that touch the database take an optional `--neon` flag. Without it
they use the local Docker Postgres; with it, the Neon `production` branch
(URLs from `.env`).

```bash
just dev                  # local Docker Postgres
just dev --neon           # same stack, pointed at Neon (local db container not started)
just migrate --neon       # migrations against Neon (direct, non-pooled URL)
just run --neon           # API on the host, outside Docker
```

`--neon` works on `dev`, `destroy`, `run`, `migrate`, `migrate-create`,
`migrate-down` and `test`. Re-run `just dev` / `just dev --neon` to switch;
Compose recreates the backend. Neon URLs come from `neon env pull`. See
`docs/decisions/0027-neon-postgres.md`.

The API will be available at [http://localhost:8000](http://localhost:8000)  
API docs at [http://localhost:8000/docs](http://localhost:8000/docs)

Re-run `just build` whenever you change backend dependencies or the Dockerfile — source code changes hot-reload automatically while `just dev` is running.

## Database Migrations

```bash
# Create a new migration after changing models
just migrate-create "add_hotels_table"

# Run pending migrations
just migrate

# Rollback last migration
just migrate-down
```

## Google sign-in

1. In the [Google Cloud console](https://console.cloud.google.com/), create an
   OAuth client of type **Web application** with the redirect URI
   `http://localhost:8000/auth/google/callback`. While the consent screen is in
   *Testing*, add your Google account as a test user.
2. Set these in `.env`:

```bash
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
SESSION_SECRET=   # openssl rand -hex 32
```

3. Open <http://localhost:8000/auth/google/login>, then check
   <http://localhost:8000/auth/me>. Every other route needs this login, and you
   only see hotels you're linked to: create one with `POST /hotels` (you're linked
   automatically), and add a colleague with `POST /hotels/{id}/users`.

For production, register `https://<api-domain>/auth/google/callback` too and
set `GOOGLE_REDIRECT_URI`, `FRONTEND_URL` and the `SESSION_*` settings (see
`.env.example`). The frontend must call the API with `credentials: "include"`.

## Code Quality

```bash
# Lint
just lint

# Format
just format

# Fix lint issues + format
just fix
```

## Pre-commit Hooks

```bash
# Install hooks (ruff formatting/linting + conventional commits)
just hooks
```

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat: add pricing endpoint`
- `fix: correct rate calculation`
- `docs: update README`

## Project Structure

```
foresight/
├── backend/
│   ├── foresight/          # Installable package (see pyproject.toml)
│   │   ├── main.py         # FastAPI app (foresight.main:app)
│   │   ├── config.py       # Settings (pydantic-settings)
│   │   ├── worker.py       # Runs background jobs
│   │   ├── routes/         # HTTP: routers and their schemas
│   │   ├── services/       # Business logic: domain, ingest, adapters, ml
│   │   ├── repository/     # Data access
│   │   └── database/       # Models, enums, session, Alembic migrations
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── docs/
│   ├── system-design.md    # How the backend fits together
│   └── decisions/          # One design decision per file
├── frontend/               # TBD
├── docker-compose.yml
├── justfile
└── .env.example
```

See [`docs/system-design.md`](docs/system-design.md) for the layers, data
model, jobs and API.

# Foresight

AI revenue intelligence platform for boutique hotels. Combines events, weather, flights, and competitor pricing to recommend optimal room rates.

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

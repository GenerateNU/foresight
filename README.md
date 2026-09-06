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
│   ├── src/
│   │   ├── main.py              # FastAPI app entrypoint
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── routes/              # API route handlers
│   │   ├── database/            # SQLAlchemy + Alembic
│   │   │   ├── base.py          # Declarative base
│   │   │   ├── session.py       # Async session factory
│   │   │   ├── models/          # SQLAlchemy models
│   │   │   └── migrations/      # Alembic migrations
│   │   └── service/             # Business logic
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                    # TBD
├── docker-compose.yml
├── justfile
├── .env.example
└── .pre-commit-config.yaml
```

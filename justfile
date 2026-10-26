set windows-shell := ["C:\\Program Files\\Git\\bin\\sh.exe", "-c"]

# Database selection: recipes that touch the database take an optional
# `--neon` flag, e.g. `just dev --neon`, `just migrate --neon`. Without it they
# use the local Docker Postgres.
_compose_local := "docker compose"
_compose_neon := "docker compose -f docker-compose.yml -f docker-compose.neon.yml"

# Host-side commands (uv run ...) read .env, which holds the Neon URLs, so
# local mode overrides them with the Docker Postgres on :5432.
_env_local := "DATABASE_URL=postgresql+asyncpg://foresight:foresight@localhost:5432/foresight_db DATABASE_URL_UNPOOLED="

# Rejects anything other than nothing or `--neon`.
[private]
_flags flags:
    @{{ if flags =~ '^(--neon)?$' { "true" } else { error("unknown flag '" + flags + "' (only --neon is supported)") } }}

# Default recipe
default:
    @just --list

# --- Backend ---

# Install backend dependencies (for local tooling/IDE support)
install:
    cd backend && uv sync

# --- Docker ---

# Build/rebuild the backend image (run after changing dependencies or the Dockerfile)
build:
    docker compose build

# Build the production backend image (no dev deps, no --reload)
build-prod:
    docker build --target prod -t foresight-backend:prod backend/

# Start all services with hot reload (`just dev --neon` to use Neon)
dev *flags: (_flags flags)
    @echo "Database: {{ if flags == "--neon" { "neon" } else { "local" } }}"
    {{ if flags == "--neon" { _compose_neon } else { _compose_local } }} up -d

# Stop all services
destroy *flags: (_flags flags)
    {{ if flags == "--neon" { _compose_neon } else { _compose_local } }} --profile local down

# Start only the database, with migrations applied
db-up:
    docker compose up -d db migrate

# Stop only the database
db-down:
    docker compose down db

# Wipe the database (drops all data, then starts a fresh instance)
db-wipe:
    docker compose stop db
    docker compose rm -f db
    docker volume rm foresight_postgres_data
    docker compose up -d db

# View backend logs
logs:
    docker compose logs -f backend

# Run the API on the host, outside Docker (`just run --neon` to use Neon)
run *flags: (_flags flags)
    @echo "Database: {{ if flags == "--neon" { "neon" } else { "local" } }}"
    cd backend && {{ if flags == "--neon" { "" } else { _env_local } }} uv run uvicorn foresight.main:app --reload --port 8000

# --- Database Migrations ---
# All take `--neon`; the default is the local Docker Postgres.

# Run all pending migrations
migrate *flags: (_flags flags)
    @echo "Database: {{ if flags == "--neon" { "neon" } else { "local" } }}"
    cd backend && {{ if flags == "--neon" { "" } else { _env_local } }} uv run alembic upgrade head

# Create a new migration (`just migrate-create "msg" --neon` to diff against Neon)
migrate-create name *flags: (_flags flags)
    cd backend && {{ if flags == "--neon" { "" } else { _env_local } }} uv run alembic revision --autogenerate -m "{{name}}"

# Rollback last migration
migrate-down *flags: (_flags flags)
    @echo "Database: {{ if flags == "--neon" { "neon" } else { "local" } }}"
    cd backend && {{ if flags == "--neon" { "" } else { _env_local } }} uv run alembic downgrade -1

# --- Users ---

# Link a user to a hotel by email (`just link-user a@b.com 1 --neon` for Neon)
link-user email hotel_id *flags: (_flags flags)
    @echo "Database: {{ if flags == "--neon" { "neon" } else { "local" } }}"
    cd backend && {{ if flags == "--neon" { "" } else { _env_local } }} uv run python -m foresight.cli link-user "{{email}}" {{hotel_id}}

# --- Testing ---

# Run the test suite
test *flags: (_flags flags)
    cd backend && {{ if flags == "--neon" { "" } else { _env_local } }} uv run pytest -q

# --- Quality ---

# Run ruff linter
lint:
    cd backend && uv run ruff check foresight/

# Run ruff formatter
format:
    cd backend && uv run ruff format foresight/

# Run ruff checks and fix
fix:
    cd backend && uv run ruff check --fix foresight/
    cd backend && uv run ruff format foresight/

# --- Pre-commit ---

# Install pre-commit hooks
hooks:
    cd backend && uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

# Run pre-commit against all tracked files
pre-commit:
    cd backend && uv run pre-commit run --all-files

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

# Start all services (db + backend with hot reload)
dev:
    docker compose up -d

# Stop all services
destroy:
    docker compose down

# Start only the database
db-up:
    docker compose up -d db

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

# --- Database Migrations ---

# Run all pending migrations
migrate:
    cd backend && uv run alembic upgrade head

# Create a new migration
migrate-create name:
    cd backend && uv run alembic revision --autogenerate -m "{{name}}"

# Rollback last migration
migrate-down:
    cd backend && uv run alembic downgrade -1

# --- Quality ---

# Run ruff linter
lint:
    cd backend && uv run ruff check src/

# Run ruff formatter
format:
    cd backend && uv run ruff format src/

# Run ruff checks and fix
fix:
    cd backend && uv run ruff check --fix src/
    cd backend && uv run ruff format src/

# --- Pre-commit ---

# Install pre-commit hooks
hooks:
    cd backend && uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

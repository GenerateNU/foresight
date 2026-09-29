# syntax=docker/dockerfile:1.7

# ---- base ------------------------------------------------------------------
# Shared foundation for both `dev` and `prod` targets. Installs Python + uv,
# then installs only the runtime dependencies of the project. Kept small and
# stable so the dependency layer caches well across source-only changes.
FROM python:3.12-slim AS base

# Pin uv to a specific version for reproducible builds. Bump deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install runtime dependencies first (cached across source changes).
# --no-install-project skips the project itself; it is installed after we
# copy the source. --no-dev omits the dev dependency group.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy source and install the `foresight` package itself (still no dev deps).
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# ---- dev -------------------------------------------------------------------
# Adds dev dependencies (pytest, ruff, ...) and runs uvicorn with --reload.
# docker-compose.yml bind-mounts ./backend/src over /app/src so edits are
# picked up live. Selected via `build.target: dev` in docker-compose.yml.
FROM base AS dev

RUN uv sync --frozen

CMD ["uv", "run", "uvicorn", "foresight.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- prod ------------------------------------------------------------------
# No dev deps, no --reload, and uvicorn is invoked directly from the venv so
# no dependency resolution runs at container start (immutable, fast boot).
# Scale workers via WEB_CONCURRENCY env or by overriding CMD in your deploy.
FROM base AS prod

CMD [".venv/bin/uvicorn", "foresight.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]

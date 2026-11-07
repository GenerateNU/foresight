#!/bin/sh
# Production start: apply migrations, then serve (decision 0050).
# If a migration fails the server never starts, so the deploy fails.
set -e
.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn foresight.main:app --host 0.0.0.0 --port 8000 --workers 1

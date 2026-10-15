# 0027. Postgres is hosted on Neon

**Status:** Accepted · **Date:** 2026-10-15

## Context
Foresight needs a managed Postgres outside the local Docker setup. Neon
(project `aged-truth-96098127`, branch `production`) provides it, configured
by `neon.ts` and linked by `.neon`.

## Decision
- The app keeps its driver: async SQLAlchemy over asyncpg, in a long-running
  FastAPI process.
- App traffic uses the pooled (`-pooler`) URL in `DATABASE_URL`, with
  `pool_pre_ping` so connections dropped by scale-to-zero are replaced.
- Alembic uses the direct URL in `DATABASE_URL_UNPOOLED`, because Neon's
  PgBouncer runs in transaction mode and migrations need a session.
- `neon env pull` writes libpq-style URLs; `config.py` converts them for
  asyncpg (`sslmode` → `ssl`, `channel_binding` dropped) so the env vars
  stay exactly as Neon writes them.

- One flag picks the database: `just <recipe> --neon` uses Neon, and no
  flag uses the local Docker Postgres. Docker uses `docker-compose.neon.yml`
  as an overlay for `--neon`, because the base compose file pins the local
  URL over `.env`. Host-side recipes override `.env`'s Neon URLs with the
  local one when `--neon` is absent.

## Consequences
- `neon env pull` refreshes credentials with no hand edits.
- Local Docker still works: with `DATABASE_URL_UNPOOLED` unset, migrations
  use `DATABASE_URL`.
- The first query after the compute idles pays a cold-start delay.

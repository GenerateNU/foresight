# 0026. The API has no authentication

**Status:** Accepted · **Date:** 2026-10-15

## Context
Foresight is in early development with one client and no frontend.

## Decision
No endpoint requires authentication.

## Consequences
- The API must not be exposed publicly as it stands.
- Adding authentication later is a routes-layer change (a FastAPI dependency).

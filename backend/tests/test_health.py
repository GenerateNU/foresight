"""Smoke test for the /health endpoint.

Runs the app in-process through httpx's ASGI transport. The transport doesn't
run the app's lifespan, so no database connection is opened.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from foresight.main import app


async def test_health_check_returns_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

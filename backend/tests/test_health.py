"""Smoke test for the /health endpoint."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from foresight.main import app


async def test_health_check_returns_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

"""Domain errors from the hotel service surface as the right HTTP status."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from foresight.database.session import get_session
from foresight.main import app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

HOTEL = {"name": "The Routed", "city": "Testville", "total_rooms": 12}


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """API client sharing the rolled-back test session."""

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def test_duplicate_hotel_is_409(client: AsyncClient) -> None:
    assert (await client.post("/hotels", json=HOTEL)).status_code == 201
    response = await client.post("/hotels", json=HOTEL)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


async def test_create_hotel_keeps_airport_codes(client: AsyncClient) -> None:
    body = HOTEL | {"airport_iata": "DUB", "airport_icao": "EIDW"}
    response = await client.post("/hotels", json=body)
    assert response.status_code == 201
    assert response.json()["airport_icao"] == "EIDW"


async def test_room_type_for_unknown_hotel_is_404(client: AsyncClient) -> None:
    body = {"hotel_id": 2**31 - 1, "name": "Twin", "room_count": 2, "base_rate": "90"}
    response = await client.post("/room-types", json=body)
    assert response.status_code == 404


async def test_duplicate_room_type_is_409(client: AsyncClient) -> None:
    hotel_id = (await client.post("/hotels", json=HOTEL)).json()["id"]
    body = {"hotel_id": hotel_id, "name": "Twin", "room_count": 2, "base_rate": "90"}
    assert (await client.post("/room-types", json=body)).status_code == 201
    assert (await client.post("/room-types", json=body)).status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "/hotels/{id}/room-types",
        "/hotels/{id}/performance",
        "/hotels/{id}/recommendations?date=2026-11-01",
    ],
)
async def test_unknown_hotel_is_404(client: AsyncClient, path: str) -> None:
    response = await client.get(path.format(id=2**31 - 1))
    assert response.status_code == 404

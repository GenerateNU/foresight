"""Shared fixtures: a rolled-back Postgres session and a hotel to price."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from foresight.config import settings
from foresight.database.models import City, Hotel, PricingModel, RoomType
from foresight.database.session import get_session
from foresight.main import app
from foresight.routes.access import get_current_user

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from foresight.database.models import User


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session whose transaction is always rolled back; skips with no Postgres."""
    # NullPool: a fresh connection per test, so none outlives its event loop.
    engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
    except (OSError, ConnectionError) as exc:
        await engine.dispose()
        pytest.skip(f"Postgres unavailable: {exc}")

    trans = await conn.begin()
    async with AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session
    await trans.rollback()
    await conn.close()
    await engine.dispose()


@dataclass(frozen=True)
class Priced:
    """Ids of a hotel set up for pricing: one room type, one active model."""

    hotel_id: int
    room_type_id: int
    model_id: int


@pytest.fixture
async def priced(session: AsyncSession) -> Priced:
    """A city, a hotel with one room type, and an active pricing model."""
    suffix = uuid.uuid4().hex[:12]
    city = City(
        name=f"Testville {suffix}",
        slug=f"testville-{suffix}",
        timezone="Europe/Dublin",
        latitude=53.35,
        longitude=-6.26,
    )
    session.add(city)
    await session.flush()

    hotel = Hotel(name="The Snapshot", city_id=city.id, total_rooms=20)
    session.add(hotel)
    await session.flush()

    room_type = RoomType(
        hotel_id=hotel.id, name="Standard", room_count=20, base_rate=Decimal("150")
    )
    model = PricingModel(
        hotel_id=hotel.id,
        version=1,
        algorithm="ebm",
        artifact=b"not a real model",  # the tests replace the model itself
        features=[],
        metrics={},
        lib_versions={},
        data_start=date(2025, 1, 1),
        data_end=date(2025, 12, 31),
        is_active=True,
    )
    session.add_all([room_type, model])
    await session.flush()
    return Priced(hotel.id, room_type.id, model.id)


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def sign_in_as(client: AsyncClient) -> Callable[[User | None], None]:
    def sign_in_as(user: User | None) -> None:
        if user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    return sign_in_as

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from foresight.repository.hotel import upsert_hotel
from foresight.repository.pricing_model import (
    activate_pricing_model,
    create_pricing_model,
    get_active_pricing_model,
    get_pricing_model,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _hotel(session: AsyncSession) -> int:
    return await upsert_hotel(
        session, name="The Modelled", city="Testville", total_rooms=20
    )


async def _create(session: AsyncSession, hotel_id: int):
    return await create_pricing_model(
        session,
        hotel_id=hotel_id,
        algorithm="ebm",
        artifact=b"fitted",
        features=["dow", "month"],
        metrics={"mae": 1.0},
        lib_versions={"interpret-core": "0.7.8"},
        data_start=date(2026, 1, 1),
        data_end=date(2026, 6, 30),
    )


async def test_versions_increment_per_hotel_and_start_inactive(session):
    hotel_id = await _hotel(session)
    first = await _create(session, hotel_id)
    second = await _create(session, hotel_id)

    assert (first.version, second.version) == (1, 2)
    assert not first.is_active
    assert await get_active_pricing_model(session, hotel_id) is None


async def test_activate_swaps_the_active_model(session):
    hotel_id = await _hotel(session)
    first = await _create(session, hotel_id)
    second = await _create(session, hotel_id)

    await activate_pricing_model(session, first.id)
    await activate_pricing_model(session, second.id)
    await session.refresh(first)

    active = await get_active_pricing_model(session, hotel_id)
    assert active is not None and active.id == second.id
    assert not first.is_active


async def test_activate_unknown_model_returns_none(session):
    assert await activate_pricing_model(session, 2**31 - 1) is None


async def test_writes_stay_in_the_callers_transaction(session):
    """The repository never commits: rolling back discards the new model."""
    hotel_id = await _hotel(session)
    model = await _create(session, hotel_id)
    model_id = model.id

    await session.rollback()

    assert await get_pricing_model(session, model_id) is None

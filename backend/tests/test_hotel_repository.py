from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.database.models.hotel import DailyPerformance, RoomType
from foresight.repository.hotel import (
    get_hotel,
    stay_date_range,
    upsert_daily_performance,
    upsert_hotel,
    upsert_room_type,
)
from foresight.repository.upsert import Outcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CITY = "Testville"


async def _hotel(session: AsyncSession, **overrides: Any) -> int:
    return await upsert_hotel(
        session, **{"name": "The Testel", "city": CITY, "total_rooms": 40} | overrides
    )


async def _room_type(session: AsyncSession, hotel_id: int, **overrides: Any) -> int:
    return await upsert_room_type(
        session,
        **{
            "hotel_id": hotel_id,
            "name": "Deluxe King",
            "room_count": 10,
            "base_rate": Decimal("180.00"),
        }
        | overrides,
    )


def _night(room_type_id: int, **overrides: Any) -> dict[str, Any]:
    return {
        "room_type_id": room_type_id,
        "stay_date": date(2026, 6, 1),
        "rate": Decimal("199.00"),
        "rooms_available": 10,
        "rooms_sold": 7,
        "room_revenue": Decimal("1393.00"),
    } | overrides


async def _nights(session: AsyncSession, room_type_id: int) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(DailyPerformance)
        .where(DailyPerformance.room_type_id == room_type_id)
    )


async def test_the_same_hotel_resolves_to_one_row(session: AsyncSession) -> None:
    assert await _hotel(session) == await _hotel(session)


async def test_room_count_updates_in_place(session: AsyncSession) -> None:
    hotel_id = await _hotel(session)
    await _hotel(session, total_rooms=45)
    hotel = await get_hotel(session, hotel_id)
    assert hotel is not None
    assert hotel.total_rooms == 45


async def test_the_same_name_in_another_city_is_a_different_hotel(
    session: AsyncSession,
) -> None:
    assert await _hotel(session) != await _hotel(session, city="Otherville")


async def test_a_room_type_resolves_to_one_row_per_hotel(
    session: AsyncSession,
) -> None:
    hotel_id = await _hotel(session)
    assert await _room_type(session, hotel_id) == await _room_type(session, hotel_id)
    assert await _room_type(session, hotel_id, name="Twin") != await _room_type(
        session, hotel_id
    )


async def test_first_night_is_new(session: AsyncSession) -> None:
    room_type_id = await _room_type(session, await _hotel(session))
    counts = await upsert_daily_performance(session, [_night(room_type_id)])
    assert counts[Outcome.NEW] == 1
    assert await _nights(session, room_type_id) == 1


async def test_identical_rerun_adds_no_rows(session: AsyncSession) -> None:
    room_type_id = await _room_type(session, await _hotel(session))
    await upsert_daily_performance(session, [_night(room_type_id)])
    counts = await upsert_daily_performance(session, [_night(room_type_id)])
    assert counts == {Outcome.NEW: 0, Outcome.UPDATED: 0, Outcome.UNCHANGED: 1}
    assert await _nights(session, room_type_id) == 1


async def test_a_resold_night_updates_in_place(session: AsyncSession) -> None:
    room_type_id = await _room_type(session, await _hotel(session))
    await upsert_daily_performance(session, [_night(room_type_id)])
    counts = await upsert_daily_performance(
        session, [_night(room_type_id, rooms_sold=9)]
    )
    assert counts[Outcome.UPDATED] == 1
    assert await _nights(session, room_type_id) == 1


async def test_an_unpriced_night_is_still_a_change(session: AsyncSession) -> None:
    # rate is nullable, so IS DISTINCT FROM has to see the drop to NULL.
    room_type_id = await _room_type(session, await _hotel(session))
    await upsert_daily_performance(session, [_night(room_type_id)])
    counts = await upsert_daily_performance(session, [_night(room_type_id, rate=None)])
    assert counts[Outcome.UPDATED] == 1


async def test_each_night_is_its_own_row(session: AsyncSession) -> None:
    room_type_id = await _room_type(session, await _hotel(session))
    await upsert_daily_performance(
        session,
        [_night(room_type_id), _night(room_type_id, stay_date=date(2026, 6, 2))],
    )
    assert await _nights(session, room_type_id) == 2


async def test_empty_batch_writes_nothing(session: AsyncSession) -> None:
    assert await upsert_daily_performance(session, []) == dict.fromkeys(Outcome, 0)


async def test_a_corrected_base_rate_wins_on_reload(session: AsyncSession) -> None:
    # The pricing model scales off base_rate, so a first-load typo must be
    # fixable rather than frozen.
    hotel_id = await _hotel(session)
    room_type_id = await _room_type(session, hotel_id)
    await _room_type(session, hotel_id, base_rate=Decimal("205.00"))
    assert await session.scalar(
        select(RoomType.base_rate).where(RoomType.id == room_type_id)
    ) == Decimal("205.00")


async def test_coordinates_are_stored_when_given(session: AsyncSession) -> None:
    hotel_id = await _hotel(session, latitude=53.3498, longitude=-6.2603)
    hotel = await get_hotel(session, hotel_id)
    assert hotel is not None
    assert (hotel.latitude, hotel.longitude) == (53.3498, -6.2603)


async def test_a_reload_without_coordinates_keeps_them(
    session: AsyncSession,
) -> None:
    # The nightly loader does not carry lat/lon, so it must not wipe what a
    # caller that does know them already stored.
    hotel_id = await _hotel(session, latitude=53.3498, longitude=-6.2603)
    await _hotel(session, total_rooms=45)
    hotel = await get_hotel(session, hotel_id)
    assert hotel is not None
    assert (hotel.latitude, hotel.longitude) == (53.3498, -6.2603)
    assert hotel.total_rooms == 45


async def test_stay_date_range_spans_every_room_type(session: AsyncSession) -> None:
    hotel_id = await _hotel(session)
    king = await _room_type(session, hotel_id)
    twin = await _room_type(session, hotel_id, name="Twin")
    await upsert_daily_performance(
        session,
        [
            _night(king, stay_date=date(2026, 6, 3)),
            _night(twin, stay_date=date(2026, 5, 30)),
        ],
    )
    assert await stay_date_range(session, hotel_id) == (
        date(2026, 5, 30),
        date(2026, 6, 3),
    )


async def test_stay_date_range_is_none_without_nights(session: AsyncSession) -> None:
    assert await stay_date_range(session, await _hotel(session)) is None

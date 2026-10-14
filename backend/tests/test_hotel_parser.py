from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
from sqlalchemy import func, select

from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.repository.upsert import Outcome
from foresight.services.adapters.hotel_csv import (
    ROOM_TYPE,
    HotelDataParser,
    persist,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CITY = "Testville"
HOTEL = "The Testel"

_NIGHTS = [
    (date(2026, 6, 1), 40, 31, 5890.0),
    (date(2026, 6, 2), 40, 28, 5320.0),
]


def _parser(nights: list[tuple[Any, ...]] | None = None) -> HotelDataParser:
    parser = HotelDataParser(
        input_path="unused.csv",
        hotel_name=HOTEL,
        city=CITY,
        base_rate=Decimal("180.00"),
    )
    # transform_data's own output shape, so no file or network is needed.
    parser.transformed_data = pd.DataFrame(
        [
            {
                "hotel_name": HOTEL,
                "stay_date": stay_date,
                "rooms_available": available,
                "rooms_sold": sold,
                "room_revenue": revenue,
            }
            for stay_date, available, sold, revenue in (nights or _NIGHTS)
        ]
    )
    return parser


def test_rows_match_the_daily_performance_columns() -> None:
    rows = _parser().rows(room_type_id=7)
    assert rows[0] == {
        "room_type_id": 7,
        "stay_date": date(2026, 6, 1),
        "rate": Decimal("190.00"),
        "rooms_available": 40,
        "rooms_sold": 31,
        "room_revenue": Decimal("5890.0"),
    }
    assert len(rows) == 2


def test_every_night_hangs_off_the_one_room_type() -> None:
    # The client reports per hotel per night, the table keys per room type per
    # night, and this is where that conversion happens.
    rows = _parser().rows(room_type_id=7)
    assert {row["room_type_id"] for row in rows} == {7}
    assert all("hotel_name" not in row for row in rows)


def test_inventory_comes_from_the_busiest_night() -> None:
    parser = _parser(
        [(date(2026, 6, 1), 38, 30, 100.0), (date(2026, 6, 2), 40, 31, 100.0)]
    )
    assert parser.total_rooms() == 40


def test_rows_before_transform_is_an_error() -> None:
    parser = HotelDataParser(
        input_path="unused.csv",
        hotel_name=HOTEL,
        city=CITY,
        base_rate=Decimal("180.00"),
    )
    with pytest.raises(ValueError):
        parser.rows(room_type_id=1)


async def test_persist_writes_through_the_repository(session: AsyncSession) -> None:
    counts = await persist(_parser(), session)
    assert counts[Outcome.NEW] == 2

    hotel_id = await session.scalar(select(Hotel.id).where(Hotel.city == CITY))
    assert hotel_id is not None
    room_type = (
        await session.execute(select(RoomType).where(RoomType.hotel_id == hotel_id))
    ).scalar_one()
    assert room_type.name == ROOM_TYPE
    assert room_type.room_count == 40
    assert room_type.base_rate == Decimal("180.00")
    assert (
        await session.scalar(
            select(func.count())
            .select_from(DailyPerformance)
            .where(DailyPerformance.room_type_id == room_type.id)
        )
        == 2
    )


async def test_reloading_the_same_file_adds_no_rows(session: AsyncSession) -> None:
    await persist(_parser(), session)
    counts = await persist(_parser(), session)
    assert counts == {Outcome.NEW: 0, Outcome.UPDATED: 0, Outcome.UNCHANGED: 2}


async def test_a_revised_night_updates_in_place(session: AsyncSession) -> None:
    await persist(_parser(), session)
    revised = [(date(2026, 6, 1), 40, 35, 6600.0), _NIGHTS[1]]
    counts = await persist(_parser(revised), session)
    assert counts[Outcome.UPDATED] == 1
    assert counts[Outcome.UNCHANGED] == 1


async def test_an_unsold_night_still_persists(session: AsyncSession) -> None:
    counts = await persist(_parser([(date(2026, 6, 1), 40, 0, 0.0)]), session)
    assert counts[Outcome.NEW] == 1


def test_an_unsold_night_has_no_rate() -> None:
    rows = _parser([(date(2026, 6, 1), 40, 0, 0.0)]).rows(room_type_id=7)
    assert rows[0]["rate"] is None

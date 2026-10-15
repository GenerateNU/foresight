"""Data access for `hotels`, `room_types` and `daily_performance`.

`create_*` returns None on a duplicate (API writes); `upsert_*` is idempotent
(loaders). Hotels are always returned with their `city` loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.repository.pagination import fetch_page
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

_PERF_KEY = ("room_type_id", "stay_date")
_PERF_MEASURES = ("rate", "rooms_available", "rooms_sold", "room_revenue")


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel | None:
    return await session.scalar(
        select(Hotel)
        .options(joinedload(Hotel.city))
        .where(Hotel.id == hotel_id)
        .execution_options(populate_existing=True)
    )


async def update_hotel(
    session: AsyncSession, hotel_id: int, changes: Mapping[str, Any]
) -> Hotel | None:
    """Apply `changes`; None if they'd duplicate another hotel's name and city.

    Runs in a savepoint so a rejected rename leaves the caller's transaction
    usable. The caller checks a new `city_id` exists.
    """
    try:
        async with session.begin_nested():
            await session.execute(
                update(Hotel).where(Hotel.id == hotel_id).values(**changes)
            )
    except IntegrityError:
        return None
    return await get_hotel(session, hotel_id)


async def upsert_room_type(
    session: AsyncSession,
    *,
    hotel_id: int,
    name: str,
    room_count: int,
    base_rate: Decimal,
) -> int:
    stmt = insert(RoomType).values(
        hotel_id=hotel_id, name=name, room_count=room_count, base_rate=base_rate
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_room_types_hotel_id_name",
        set_={
            "room_count": stmt.excluded.room_count,
            # base_rate is the hotel's stated normal price (the export has none),
            # so a reload correcting it has to win rather than be dropped.
            "base_rate": stmt.excluded.base_rate,
        },
    ).returning(RoomType.id)
    return (await session.execute(stmt)).scalar_one()


async def upsert_daily_performance(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (room_type_id, stay_date)."""
    return await upsert_rows(
        session,
        DailyPerformance,
        constraint="uq_daily_performance_room_type_id_stay_date",
        key=_PERF_KEY,
        mutable=_PERF_MEASURES,
        rows=rows,
    )


async def create_hotel(
    session: AsyncSession,
    *,
    name: str,
    city_id: int,
    total_rooms: int,
    latitude: float | None,
    longitude: float | None,
) -> Hotel | None:
    """Insert a hotel; None if one with this name already exists in the city.

    The caller checks `city_id` exists.
    """
    hotel_id = await session.scalar(
        insert(Hotel)
        .values(
            name=name,
            city_id=city_id,
            total_rooms=total_rooms,
            latitude=latitude,
            longitude=longitude,
        )
        .on_conflict_do_nothing(constraint="uq_hotels_city_id_name")
        .returning(Hotel.id)
    )
    return None if hotel_id is None else await get_hotel(session, hotel_id)


async def create_room_type(
    session: AsyncSession,
    *,
    hotel_id: int,
    name: str,
    room_count: int,
    base_rate: Decimal,
) -> RoomType | None:
    """Insert a room type; None if the hotel already has one with this name."""
    return await session.scalar(
        insert(RoomType)
        .values(
            hotel_id=hotel_id, name=name, room_count=room_count, base_rate=base_rate
        )
        .on_conflict_do_nothing(constraint="uq_room_types_hotel_id_name")
        .returning(RoomType)
    )


async def list_hotels(session: AsyncSession) -> Sequence[Hotel]:
    stmt = select(Hotel).options(joinedload(Hotel.city)).order_by(Hotel.id)
    return (await session.scalars(stmt)).all()


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType | None:
    return await session.get(RoomType, room_type_id)


async def list_room_types(session: AsyncSession, hotel_id: int) -> Sequence[RoomType]:
    stmt = select(RoomType).where(RoomType.hotel_id == hotel_id).order_by(RoomType.id)
    return (await session.scalars(stmt)).all()


async def list_performance(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date | None,
    end: date | None,
    room_type_id: int | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[DailyPerformance], int]:
    """Nights for every room type of a hotel; `daily_performance` has no hotel_id."""
    stmt = (
        select(DailyPerformance)
        .join(RoomType, DailyPerformance.room_type_id == RoomType.id)
        .where(RoomType.hotel_id == hotel_id)
    )
    if room_type_id is not None:
        stmt = stmt.where(DailyPerformance.room_type_id == room_type_id)
    if start is not None:
        stmt = stmt.where(DailyPerformance.stay_date >= start)
    if end is not None:
        stmt = stmt.where(DailyPerformance.stay_date <= end)
    stmt = stmt.order_by(DailyPerformance.stay_date, DailyPerformance.room_type_id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def stay_date_range(
    session: AsyncSession, hotel_id: int
) -> tuple[date, date] | None:
    """First and last stay_date loaded for a hotel, or None if it has no nights."""
    first, last = (
        await session.execute(
            select(
                func.min(DailyPerformance.stay_date),
                func.max(DailyPerformance.stay_date),
            )
            .join(RoomType, DailyPerformance.room_type_id == RoomType.id)
            .where(RoomType.hotel_id == hotel_id)
        )
    ).one()
    return None if first is None else (first, last)

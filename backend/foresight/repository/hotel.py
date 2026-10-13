from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.repository import Outcome, upsert_rows
from foresight.repository.pagination import fetch_page

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

_PERF_KEY = ("room_type_id", "stay_date")
_PERF_MEASURES = ("rate", "rooms_available", "rooms_sold", "room_revenue")


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel | None:
    return await session.get(Hotel, hotel_id)


async def upsert_hotel(
    session: AsyncSession,
    *,
    name: str,
    city: str,
    total_rooms: int,
    latitude: float | None = None,
    longitude: float | None = None,
) -> int:
    """Return the id of the hotel named `name` in `city`, creating it if new."""
    stmt = insert(Hotel).values(
        name=name,
        city=city,
        total_rooms=total_rooms,
        latitude=latitude,
        longitude=longitude,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_hotels_name_city",
        set_={
            "total_rooms": stmt.excluded.total_rooms,
            # Coordinates are optional, so a caller that omits them must not
            # erase what another caller already stored.
            "latitude": func.coalesce(stmt.excluded.latitude, Hotel.latitude),
            "longitude": func.coalesce(stmt.excluded.longitude, Hotel.longitude),
        },
    ).returning(Hotel.id)
    return (await session.execute(stmt)).scalar_one()


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
        constraint="uq_room_types_hotel_name",
        set_={
            "room_count": stmt.excluded.room_count,
            # The pricing model scales off base_rate, so a reload correcting it
            # has to win rather than be silently dropped.
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
        cast("Table", DailyPerformance.__table__),
        constraint="uq_daily_performance_room_type_stay",
        key=_PERF_KEY,
        mutable=_PERF_MEASURES,
        rows=rows,
    )


async def create_hotel(
    session: AsyncSession,
    *,
    name: str,
    city: str,
    total_rooms: int,
    latitude: float | None,
    longitude: float | None,
) -> Hotel:
    hotel = Hotel(
        name=name,
        city=city,
        total_rooms=total_rooms,
        latitude=latitude,
        longitude=longitude,
    )
    session.add(hotel)
    await session.flush()
    await session.refresh(hotel)
    return hotel


async def create_room_type(
    session: AsyncSession,
    *,
    hotel_id: int,
    name: str,
    room_count: int,
    base_rate: Decimal,
) -> RoomType:
    room_type = RoomType(
        hotel_id=hotel_id, name=name, room_count=room_count, base_rate=base_rate
    )
    session.add(room_type)
    await session.flush()
    await session.refresh(room_type)
    return room_type


async def list_hotels(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[Sequence[Hotel], int]:
    return await fetch_page(
        session, select(Hotel).order_by(Hotel.id), limit=limit, offset=offset
    )


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType | None:
    return await session.get(RoomType, room_type_id)


async def list_room_types(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[RoomType], int]:
    stmt = select(RoomType).where(RoomType.hotel_id == hotel_id).order_by(RoomType.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)


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

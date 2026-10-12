"""Data access for hotels, room types and their daily performance."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.repository.pagination import fetch_page


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
    await session.commit()
    await session.refresh(hotel)
    return hotel


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel | None:
    return await session.get(Hotel, hotel_id)


async def list_hotels(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[Sequence[Hotel], int]:
    return await fetch_page(
        session, select(Hotel).order_by(Hotel.id), limit=limit, offset=offset
    )


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
    await session.commit()
    await session.refresh(room_type)
    return room_type


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

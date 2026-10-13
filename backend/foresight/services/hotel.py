"""Hotels, their room types, and nightly performance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import hotel as hotel_repo
from foresight.services.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
    from foresight.schemas.hotel import HotelRequest, RoomTypeRequest


async def create_hotel(session: AsyncSession, data: HotelRequest) -> Hotel:
    """Raises ConflictError if a hotel with this name already exists in the city."""
    hotel = await hotel_repo.create_hotel(
        session,
        name=data.name,
        city=data.city,
        total_rooms=data.total_rooms,
        latitude=data.latitude,
        longitude=data.longitude,
        airport_iata=data.airport_iata,
        airport_icao=data.airport_icao,
        timezone=data.timezone,
    )
    if hotel is None:
        raise ConflictError(f"Hotel {data.name!r} already exists in {data.city}")
    return hotel


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel | None:
    return await hotel_repo.get_hotel(session, hotel_id)


async def require_hotel(session: AsyncSession, hotel_id: int) -> Hotel:
    """The hotel, or NotFoundError. For operations that can't run without one."""
    hotel = await hotel_repo.get_hotel(session, hotel_id)
    if hotel is None:
        raise NotFoundError("Hotel", hotel_id)
    return hotel


async def list_hotels(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[Sequence[Hotel], int]:
    return await hotel_repo.list_hotels(session, limit=limit, offset=offset)


async def create_room_type(session: AsyncSession, data: RoomTypeRequest) -> RoomType:
    """Raises NotFoundError for an unknown hotel, ConflictError for a duplicate."""
    await require_hotel(session, data.hotel_id)
    room_type = await hotel_repo.create_room_type(
        session,
        hotel_id=data.hotel_id,
        name=data.name,
        room_count=data.room_count,
        base_rate=data.base_rate,
    )
    if room_type is None:
        raise ConflictError(
            f"Hotel {data.hotel_id} already has a room type named {data.name!r}"
        )
    return room_type


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType | None:
    return await hotel_repo.get_room_type(session, room_type_id)


async def list_room_types(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[RoomType], int]:
    await require_hotel(session, hotel_id)
    return await hotel_repo.list_room_types(
        session, hotel_id, limit=limit, offset=offset
    )


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
    await require_hotel(session, hotel_id)
    return await hotel_repo.list_performance(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_id=room_type_id,
        limit=limit,
        offset=offset,
    )

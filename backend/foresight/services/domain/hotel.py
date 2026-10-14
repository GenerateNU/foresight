"""Hotels, their room types, and nightly performance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from foresight.repository import hotel as hotel_repo
from foresight.services.domain.city import get_city
from foresight.services.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType


async def create_hotel(
    session: AsyncSession,
    *,
    name: str,
    city_id: int,
    total_rooms: int,
    latitude: float | None,
    longitude: float | None,
) -> Hotel:
    """Raises NotFoundError for an unknown city, ConflictError if the city
    already has a hotel with this name."""
    city = await get_city(session, city_id)
    hotel = await hotel_repo.create_hotel(
        session,
        name=name,
        city_id=city_id,
        total_rooms=total_rooms,
        latitude=latitude,
        longitude=longitude,
    )
    if hotel is None:
        raise ConflictError(f"Hotel {name!r} already exists in {city.name}")
    return hotel


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel:
    """The hotel with its city loaded. Raises NotFoundError for an unknown hotel."""
    hotel = await hotel_repo.get_hotel(session, hotel_id)
    if hotel is None:
        raise NotFoundError("Hotel", hotel_id)
    return hotel


async def update_hotel(
    session: AsyncSession, hotel_id: int, changes: dict[str, Any]
) -> Hotel:
    """Change only the fields given.

    Raises:
        NotFoundError: Unknown hotel, or unknown new city.
        ConflictError: The new name and city match another hotel.
    """
    hotel = await get_hotel(session, hotel_id)
    if not changes:
        return hotel
    if "city_id" in changes:
        await get_city(session, changes["city_id"])
    updated = await hotel_repo.update_hotel(session, hotel_id, changes)
    if updated is None:
        name = changes.get("name", hotel.name)
        raise ConflictError(f"Hotel {name!r} already exists in that city")
    return updated


async def list_hotels(session: AsyncSession) -> Sequence[Hotel]:
    return await hotel_repo.list_hotels(session)


async def create_room_type(
    session: AsyncSession,
    hotel_id: int,
    *,
    name: str,
    room_count: int,
    base_rate: Decimal,
) -> RoomType:
    """Raises NotFoundError for an unknown hotel, ConflictError for a duplicate."""
    await get_hotel(session, hotel_id)
    room_type = await hotel_repo.create_room_type(
        session,
        hotel_id=hotel_id,
        name=name,
        room_count=room_count,
        base_rate=base_rate,
    )
    if room_type is None:
        raise ConflictError(f"Hotel {hotel_id} already has a room type named {name!r}")
    return room_type


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType:
    """Raises NotFoundError for an unknown room type."""
    room_type = await hotel_repo.get_room_type(session, room_type_id)
    if room_type is None:
        raise NotFoundError("Room type", room_type_id)
    return room_type


async def list_room_types(session: AsyncSession, hotel_id: int) -> Sequence[RoomType]:
    await get_hotel(session, hotel_id)
    return await hotel_repo.list_room_types(session, hotel_id)


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
    await get_hotel(session, hotel_id)
    return await hotel_repo.list_performance(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_id=room_type_id,
        limit=limit,
        offset=offset,
    )

"""Hotels and their room types."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.hotel import Hotel, RoomType
from foresight.database.models.user import User
from foresight.repository import hotel as hotel_repo
from foresight.repository import user as user_repo
from foresight.services.domain.city import get_city
from foresight.services.errors import ConflictError, NotFoundError


async def create_hotel(
    session: AsyncSession,
    *,
    name: str,
    city_id: int,
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
        latitude=latitude,
        longitude=longitude,
    )
    if hotel is None:
        raise ConflictError(f"Hotel {name!r} already exists in {city.name}")
    return hotel


async def create_hotel_for_user(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    city_id: int,
    latitude: float | None,
    longitude: float | None,
) -> Hotel:
    """`create_hotel`, then link the creator so the hotel isn't unreachable.
    Raises the same errors."""
    hotel = await create_hotel(
        session,
        name=name,
        city_id=city_id,
        latitude=latitude,
        longitude=longitude,
    )
    await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)
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


async def list_hotels_for_user(session: AsyncSession, user_id: int) -> Sequence[Hotel]:
    """The hotels this user works for, with their cities loaded. A user linked to
    none gets an empty list; the caller has already established the user exists."""
    return await hotel_repo.list_hotels_for_user(session, user_id)


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType:
    """Raises NotFoundError for an unknown room type."""
    room_type = await hotel_repo.get_room_type(session, room_type_id)
    if room_type is None:
        raise NotFoundError("Room type", room_type_id)
    return room_type

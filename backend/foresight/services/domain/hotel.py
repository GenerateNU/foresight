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
    """Creates a hotel.

    Args:
        session (AsyncSession): The database session.
        name (str): The hotel's name, unique in its city.
        city_id (int): Its city.
        latitude (float | None): Where it is, if known.
        longitude (float | None): Where it is, if known.

    Returns:
        Hotel: The new hotel.

    Raises:
        NotFoundError: The city doesn't exist.
        ConflictError: The city already has a hotel with this name.
    """
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
    """Creates a hotel and links its creator, so it isn't unreachable.

    Args:
        session (AsyncSession): The database session.
        user (User): The creator.
        name (str): The hotel's name, unique in its city.
        city_id (int): Its city.
        latitude (float | None): Where it is, if known.
        longitude (float | None): Where it is, if known.

    Returns:
        Hotel: The new hotel.

    Raises:
        NotFoundError: The city doesn't exist.
        ConflictError: The city already has a hotel with this name.
    """
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
    """Gets a hotel with its city loaded.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        Hotel: The hotel.

    Raises:
        NotFoundError: The hotel doesn't exist.
    """
    hotel = await hotel_repo.get_hotel(session, hotel_id)
    if hotel is None:
        raise NotFoundError("Hotel", hotel_id)
    return hotel


async def update_hotel(
    session: AsyncSession, hotel_id: int, changes: dict[str, Any]
) -> Hotel:
    """Changes only the fields given.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        changes (dict[str, Any]): New values by column name.

    Returns:
        Hotel: The updated hotel.

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
    """Lists every hotel.

    Args:
        session (AsyncSession): The database session.

    Returns:
        Sequence[Hotel]: The hotels.
    """
    return await hotel_repo.list_hotels(session)


async def list_hotels_for_user(session: AsyncSession, user_id: int) -> Sequence[Hotel]:
    """Lists the hotels a user works for, with their cities loaded.

    The caller has already established that the user exists.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.

    Returns:
        Sequence[Hotel]: The hotels; empty for a user linked to none.
    """
    return await hotel_repo.list_hotels_for_user(session, user_id)


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType:
    """Gets a room type.

    Args:
        session (AsyncSession): The database session.
        room_type_id (int): The room type.

    Returns:
        RoomType: The room type.

    Raises:
        NotFoundError: The room type doesn't exist.
    """
    room_type = await hotel_repo.get_room_type(session, room_type_id)
    if room_type is None:
        raise NotFoundError("Room type", room_type_id)
    return room_type

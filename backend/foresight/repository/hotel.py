from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from foresight.database.models.hotel import Hotel, RoomType
from foresight.database.models.user import UserHotel


async def create_hotel(
    session: AsyncSession,
    *,
    name: str,
    city_id: int,
    latitude: float | None,
    longitude: float | None,
) -> Hotel | None:
    """Inserts a hotel; the caller checks the city exists.

    Args:
        session (AsyncSession): The database session.
        name (str): The hotel's name.
        city_id (int): Its city.
        latitude (float | None): The hotel itself.
        longitude (float | None): The hotel itself.

    Returns:
        Hotel | None: The new hotel with its city, or None if the city already
            has a hotel with this name.
    """
    hotel_id = await session.scalar(
        insert(Hotel)
        .values(name=name, city_id=city_id, latitude=latitude, longitude=longitude)
        .on_conflict_do_nothing(constraint="uq_hotels_city_id_name")
        .returning(Hotel.id)
    )
    return None if hotel_id is None else await get_hotel(session, hotel_id)


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel | None:
    """Gets a hotel with its city loaded.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        Hotel | None: The hotel, or None if it doesn't exist.
    """
    return await session.scalar(
        select(Hotel)
        .options(joinedload(Hotel.city))
        .where(Hotel.id == hotel_id)
        .execution_options(populate_existing=True)
    )


async def list_hotels(session: AsyncSession) -> Sequence[Hotel]:
    """Lists every hotel with its city loaded.

    Args:
        session (AsyncSession): The database session.

    Returns:
        Sequence[Hotel]: The hotels, by id.
    """
    stmt = select(Hotel).options(joinedload(Hotel.city)).order_by(Hotel.id)
    return (await session.scalars(stmt)).all()


async def list_hotels_for_user(session: AsyncSession, user_id: int) -> Sequence[Hotel]:
    """Lists the hotels a user is linked to, with their cities loaded.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.

    Returns:
        Sequence[Hotel]: The hotels, by id; empty for a user with none.
    """
    stmt = (
        select(Hotel)
        .join(UserHotel, UserHotel.hotel_id == Hotel.id)
        .where(UserHotel.user_id == user_id)
        .options(joinedload(Hotel.city))
        .order_by(Hotel.id)
    )
    return (await session.scalars(stmt)).all()


async def update_hotel(
    session: AsyncSession, hotel_id: int, changes: Mapping[str, Any]
) -> Hotel | None:
    """Changes a hotel's columns; the caller checks a new city exists.

    Runs in a savepoint, so a rejected rename leaves the caller's transaction
    usable.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        changes (Mapping[str, Any]): The columns to change.

    Returns:
        Hotel | None: The hotel with its city, or None if the change would
            duplicate another hotel's name in its city.
    """
    try:
        async with session.begin_nested():
            await session.execute(
                update(Hotel).where(Hotel.id == hotel_id).values(**changes)
            )
    except IntegrityError:
        return None
    return await get_hotel(session, hotel_id)


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType | None:
    """Gets a room type.

    Args:
        session (AsyncSession): The database session.
        room_type_id (int): The room type.

    Returns:
        RoomType | None: The room type, or None if it doesn't exist.
    """
    return await session.get(RoomType, room_type_id)


async def find_room_type(
    session: AsyncSession, hotel_id: int, name: str
) -> RoomType | None:
    """Finds the hotel's room type with a name.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        name (str): The room type's name.

    Returns:
        RoomType | None: The room type, or None if there isn't one.
    """
    return await session.scalar(
        select(RoomType).where(RoomType.hotel_id == hotel_id, RoomType.name == name)
    )


async def get_or_create_room_type(
    session: AsyncSession, *, hotel_id: int, name: str
) -> RoomType:
    """Gets the hotel's room type with a name, creating it if needed.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        name (str): The room type's name.

    Returns:
        RoomType: The room type.
    """
    await session.execute(
        insert(RoomType)
        .values(hotel_id=hotel_id, name=name)
        .on_conflict_do_nothing(constraint="uq_room_types_hotel_id_name")
    )
    room_type = await find_room_type(session, hotel_id, name)
    assert room_type is not None
    return room_type

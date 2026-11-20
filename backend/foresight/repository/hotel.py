"""Data access for `hotels` and `room_types`.

`create_*` returns None on a duplicate (API writes); `upsert_*` is idempotent
(loaders). Hotels are always returned with their `city` loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from foresight.database.models.hotel import Hotel, RoomType
from foresight.database.models.user import UserHotel

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


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


async def get_or_create_room_type(
    session: AsyncSession, *, hotel_id: int, name: str
) -> RoomType:
    """The hotel's room type with this name, created if it doesn't exist."""
    await session.execute(
        insert(RoomType)
        .values(hotel_id=hotel_id, name=name)
        .on_conflict_do_nothing(constraint="uq_room_types_hotel_id_name")
    )
    return await session.scalar(
        select(RoomType).where(RoomType.hotel_id == hotel_id, RoomType.name == name)
    )


async def create_hotel(
    session: AsyncSession,
    *,
    name: str,
    city_id: int,
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
) -> RoomType | None:
    """Insert a room type; None if the hotel already has one with this name."""
    return await session.scalar(
        insert(RoomType)
        .values(hotel_id=hotel_id, name=name)
        .on_conflict_do_nothing(constraint="uq_room_types_hotel_id_name")
        .returning(RoomType)
    )


async def list_hotels(session: AsyncSession) -> Sequence[Hotel]:
    stmt = select(Hotel).options(joinedload(Hotel.city)).order_by(Hotel.id)
    return (await session.scalars(stmt)).all()


async def list_hotels_for_user(session: AsyncSession, user_id: int) -> Sequence[Hotel]:
    """The hotels a user is linked to; empty for a user with none."""
    stmt = (
        select(Hotel)
        .join(UserHotel, UserHotel.hotel_id == Hotel.id)
        .where(UserHotel.user_id == user_id)
        .options(joinedload(Hotel.city))
        .order_by(Hotel.id)
    )
    return (await session.scalars(stmt)).all()


async def find_room_type(
    session: AsyncSession, hotel_id: int, name: str
) -> RoomType | None:
    """The hotel's room type with this name, or None."""
    return await session.scalar(
        select(RoomType).where(RoomType.hotel_id == hotel_id, RoomType.name == name)
    )


async def get_room_type(session: AsyncSession, room_type_id: int) -> RoomType | None:
    return await session.get(RoomType, room_type_id)


async def list_room_types(session: AsyncSession, hotel_id: int) -> Sequence[RoomType]:
    stmt = select(RoomType).where(RoomType.hotel_id == hotel_id).order_by(RoomType.id)
    return (await session.scalars(stmt)).all()

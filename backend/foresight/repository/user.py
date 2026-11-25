from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.hotel import Hotel
from foresight.database.models.user import User, UserHotel


async def upsert_user(
    session: AsyncSession, *, google_id: str, email: str, name: str | None
) -> User:
    """Creates the user for a Google account, or refreshes the one that exists.

    A sign-in refreshes the email and name and stamps `last_signed_in_at`. One
    statement, so two sign-ins at once can't both insert.

    Args:
        session (AsyncSession): The database session.
        google_id (str): Google's account id.
        email (str): The account's email.
        name (str | None): The account's name.

    Returns:
        User: The user.
    """
    stmt = insert(User).values(google_id=google_id, email=email, name=name)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_users_google_id",
        set_={
            "email": stmt.excluded.email,
            "name": stmt.excluded.name,
            "last_signed_in_at": func.now(),
        },
    )
    user = await session.scalar(
        stmt.returning(User).execution_options(populate_existing=True)
    )
    assert user is not None
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    """Gets a user.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.

    Returns:
        User | None: The user, or None if they don't exist.
    """
    return await session.get(User, user_id)


async def list_users_by_email(session: AsyncSession, email: str) -> Sequence[User]:
    """Lists the users with an email, ignoring case.

    Args:
        session (AsyncSession): The database session.
        email (str): The email.

    Returns:
        Sequence[User]: The users, by id; email isn't unique, so there can be
            several.
    """
    stmt = select(User).where(func.lower(User.email) == email.lower()).order_by(User.id)
    return (await session.scalars(stmt)).all()


async def link_hotel(session: AsyncSession, *, user_id: int, hotel_id: int) -> bool:
    """Links a user to a hotel; the caller checks both exist.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.
        hotel_id (int): The hotel.

    Returns:
        bool: True if the link is new, False if it already existed.
    """
    linked = await session.scalar(
        insert(UserHotel)
        .values(user_id=user_id, hotel_id=hotel_id)
        .on_conflict_do_nothing(constraint="pk_user_hotels")
        .returning(UserHotel.user_id)
    )
    return linked is not None


async def has_hotel(session: AsyncSession, user_id: int, hotel_id: int) -> bool:
    """Checks whether a user is linked to a hotel.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.
        hotel_id (int): The hotel.

    Returns:
        bool: Whether they're linked.
    """
    stmt = select(UserHotel.user_id).where(
        UserHotel.user_id == user_id, UserHotel.hotel_id == hotel_id
    )
    return await session.scalar(stmt) is not None


async def has_hotel_in_city(session: AsyncSession, user_id: int, city_id: int) -> bool:
    """Checks whether a user is linked to at least one hotel in a city.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.
        city_id (int): The city.

    Returns:
        bool: Whether they are.
    """
    stmt = (
        select(UserHotel.user_id)
        .join(Hotel, Hotel.id == UserHotel.hotel_id)
        .where(UserHotel.user_id == user_id, Hotel.city_id == city_id)
        .limit(1)
    )
    return await session.scalar(stmt) is not None

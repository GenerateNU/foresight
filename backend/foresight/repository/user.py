"""Data access for `users` and `user_hotels`.

`create_user` returns None when the Google account already has a user.
`link_hotel` is idempotent: it reports whether it added a link or one was
already there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from foresight.database.models.user import User, UserHotel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


async def create_user(
    session: AsyncSession, *, google_id: str, email: str, name: str | None
) -> User | None:
    """Insert a user; None if this Google account already has one."""
    return await session.scalar(
        insert(User)
        .values(google_id=google_id, email=email, name=name)
        .on_conflict_do_nothing(constraint="uq_users_google_id")
        .returning(User)
    )


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_google_id(session: AsyncSession, google_id: str) -> User | None:
    return await session.scalar(select(User).where(User.google_id == google_id))


async def list_users_by_email(session: AsyncSession, email: str) -> Sequence[User]:
    """Users with this email, ignoring case. Email isn't unique, so there can be
    several."""
    stmt = select(User).where(func.lower(User.email) == email.lower()).order_by(User.id)
    return (await session.scalars(stmt)).all()


async def link_hotel(session: AsyncSession, *, user_id: int, hotel_id: int) -> bool:
    """Link a user to a hotel. True if the link is new, False if it already
    existed. The caller checks both exist."""
    linked = await session.scalar(
        insert(UserHotel)
        .values(user_id=user_id, hotel_id=hotel_id)
        .on_conflict_do_nothing(constraint="pk_user_hotels")
        .returning(UserHotel.user_id)
    )
    return linked is not None


async def list_hotel_ids(session: AsyncSession, user_id: int) -> Sequence[int]:
    stmt = (
        select(UserHotel.hotel_id)
        .where(UserHotel.user_id == user_id)
        .order_by(UserHotel.hotel_id)
    )
    return (await session.scalars(stmt)).all()

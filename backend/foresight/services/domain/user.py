"""Users, and which hotels they work for."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import user as user_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.user import User


async def create_user(
    session: AsyncSession, *, google_id: str, email: str, name: str | None
) -> User:
    """Raises ConflictError if this Google account already has a user."""
    user = await user_repo.create_user(
        session, google_id=google_id, email=email, name=name
    )
    if user is None:
        raise ConflictError(f"A user already exists for Google account {google_id!r}")
    return user


async def get_user(session: AsyncSession, user_id: int) -> User:
    """Raises NotFoundError for an unknown user."""
    user = await user_repo.get_user(session, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    return user


async def get_user_by_google_id(session: AsyncSession, google_id: str) -> User:
    """Raises NotFoundError if no user has this Google account id."""
    user = await user_repo.get_user_by_google_id(session, google_id)
    if user is None:
        raise NotFoundError("User", google_id)
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User:
    """The user with this email, ignoring case.

    Raises:
        NotFoundError: No user has this email.
        ConflictError: Several do. Emails change hands, so this never picks one:
            it would give a hotel's access to the wrong person.
    """
    users = await user_repo.list_users_by_email(session, email)
    if not users:
        raise NotFoundError("User", email)
    if len(users) > 1:
        raise ConflictError(f"More than one user has the email {email!r}")
    return users[0]


async def link_user_to_hotel(
    session: AsyncSession, *, user_id: int, hotel_id: int
) -> bool:
    """Link a user to a hotel. True if the link is new, False if it already
    existed; linking twice is not an error.

    Raises NotFoundError for an unknown user or hotel.
    """
    await get_user(session, user_id)
    await get_hotel(session, hotel_id)
    return await user_repo.link_hotel(session, user_id=user_id, hotel_id=hotel_id)


async def list_hotel_ids(session: AsyncSession, user_id: int) -> Sequence[int]:
    """The hotels a user is linked to. Raises NotFoundError for an unknown user."""
    await get_user(session, user_id)
    return await user_repo.list_hotel_ids(session, user_id)

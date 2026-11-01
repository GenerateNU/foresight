"""Users, and which hotels they work for."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.config import settings
from foresight.repository import user as user_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.errors import (
    ConflictError,
    ForbiddenError,
    NotConfiguredError,
    NotFoundError,
    NotSignedInError,
)

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


def require_sign_in_configured() -> None:
    """Raises NotConfiguredError if a Google or session setting is missing."""
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("SESSION_SECRET", settings.session_secret),
        )
        if not value
    ]
    if missing:
        raise NotConfiguredError(f"{', '.join(missing)} not set on the server")


async def sign_in(
    session: AsyncSession,
    *,
    google_id: str | None,
    email: str | None,
    email_verified: bool,
    name: str | None,
) -> User:
    """Find or create the user for a Google account and record the sign-in.

    Raises ForbiddenError if Google gave no id or email, or didn't verify it.
    """
    if not google_id or not email or not email_verified:
        raise ForbiddenError("Google did not confirm a verified email for this account")
    return await user_repo.upsert_user(
        session, google_id=google_id, email=email, name=name
    )


async def get_signed_in_user(session: AsyncSession, user_id: object) -> User:
    """The user a session belongs to. Raises NotSignedInError if there isn't one."""
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise NotSignedInError("Not signed in")
    user = await user_repo.get_user(session, user_id)
    if user is None:
        raise NotSignedInError("Not signed in")
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


async def link_user_by_email(
    session: AsyncSession, *, hotel_id: int, email: str
) -> bool:
    """Link the user who has this email to a hotel. True if the link is new.

    Raises NotFoundError if nobody with this email has signed in yet (or the
    hotel is unknown), ConflictError if several users share it. The caller has
    checked that whoever is linking may reach the hotel.
    """
    user = await get_user_by_email(session, email)
    return await link_user_to_hotel(session, user_id=user.id, hotel_id=hotel_id)


async def list_hotel_ids(session: AsyncSession, user_id: int) -> Sequence[int]:
    """The hotels a user is linked to. Raises NotFoundError for an unknown user."""
    await get_user(session, user_id)
    return await user_repo.list_hotel_ids(session, user_id)
